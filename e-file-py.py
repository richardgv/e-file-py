#! /usr/bin/env python3

# Richard Grenville
# https://github.com/richardgv/e-file-py
# Distributed under the terms of the GNU General Public License v2+

import urllib.request, urllib.parse, argparse, sys, os, functools, gzip

try: import portage
except ImportError: pass

# Helper functions

# http://stackoverflow.com/a/1695250
def enum_build(*sequential, **named):
    enums = dict(zip(sequential, range(len(sequential))), **named)
    return type('Enum', (), enums)

def report(level, msg):
	'''Logging function.'''
	if LOGLEVELS.fatal == level:
		msg = 'FATAL: ' + msg
	elif LOGLEVELS.warning == level:
		msg = 'WARNING: ' + msg
	elif LOGLEVELS.info == level:
		msg = 'INFO: ' + msg
	elif LOGLEVELS.debug == level:
		msg = 'DEBUG: ' + msg
	if conf['loglevel'] >= level:
		print(msg, file = sys.stderr)
	if LOGLEVELS.fatal == level:
		quit(5)
	return 0

def dbg_write(id, content):
	'''Write some contents to a temporary file for debugging.'''
	if not conf['debug']:
		return
	with open('/tmp/' + id, 'w') as f:
		f.write(content)

def sys_detect():
	if 'portage' in sys.modules:
		return 'gentoo'
	return None

def commasplit(str_src):
	return [ item.strip() for item
			in str_src.split(',') if item.strip() ]

def plist_getver(plist):
	return [ portage.versions.cpv_getversion(p) for p in plist ]

def get_vercmp_func():
	if 'gentoo' == system:
		return portage.versions.vercmp
	else:
		return (lambda a, b: (a > b) - 0.5)

def ver_validate(ver):
	# Ugly hack to deal with some broken package versions
	# PFL reports
	if '.' == ver[-1]:
		ver = ver[:-1]
	if 'gentoo' == system and not portage.versions.ververify(ver):
		report(LOGLEVELS.warning, 'Invalid version number: {}'.format(ver))
		ver = '0'
	return ver

def process_cp(arg):
	if -1 == arg.find('/'):
		if 'gentoo' != system:
			report(LOGLEVELS.fatal,
					'Without Portage API I could not expand package names.')
		arg = portage.dep_expand(arg, db_port)
		if arg.startswith('null/'):
			report(LOGLEVELS.fatal, 'Failed to expand package name to CP.')
	return tuple(arg.split('/', 1))

def process_cpv(arg):
	if 'gentoo' != system:
		report(LOGLEVELS.fatal, 'Without Portage API I could not split CPV.')
	cp = portage.versions.pkgsplit(arg)[0]
	ver = arg[len(cp) + 1:]
	return tuple(process_cp(cp)) + (ver, )

def process_args_cp(args):
	if 2 < len(args):
		report(LOGLEVELS.warning, 'I see too many arguments.')
		args = args[0:2]
	if 1 == len(args):
		return process_cp(args[0])
	else:
		return tuple(args)

def process_args_cpv(args):
	if 3 < len(args):
		report(LOGLEVELS.warning, 'I see too many arguments.')
		args = args[0:3]
	if 1 == len(args):
		return process_cpv(args[0])
	elif 2 == len(args):
		return process_cp(args[0]) + (args[1], )
	else:
		return tuple(args)

# Default configurations

LOGLEVELS_STRS = ('fatal', 'warning', 'info', 'debug')
LOGLEVELS = enum_build(*LOGLEVELS_STRS)

SOURCES = ('pfl_html', 'pfl_json')

PREDEF_FMTSTR = dict(
		base = dict(
			lvcp = '',
			lvver = '',
			lvpath = '',
			sep_lvcp = '\n',
			sep_lvver = '',
			sep_lvpath = '',
			sep = ', ',
			sym_ = ' * ',
			sym_installed = '[I]',
			sym_upgrade = '[U]',
			sym_downgrade = '[D]',
			prefix_installed = '\033[0;32m\033[7m',
			suffix_installed = '\033[0m',
			prefix_available = '\033[0;44m',
			suffix_available = '\033[0m',
			prefix_matched = '\033[0;44m',
			suffix_matched = '\033[0m',
			prefix_exists = '\033[0;32m\033[7m',
			suffix_exists = '\033[0m',
			repr_true_exists = 'Exists',
			repr_false_exists = 'Does not exist',
			repr_empty_installed = 'Not installed',
			repr_empty_ver_installed = '[ Not Installed ]',
			repr_empty_ver_available = '[ Not Available ]',
			repr_empty_ver_all = '[ No Information ]',
			repr_empty_ver = '[ No Information ]',
			noresult = 'Sorry, no results found.\n',
		),
		e_file_uniq = dict(
			lvcp = '{symbol} {c}/\033[1m{p}\033[0m\n'
			'{lvcp_sub_aux_if_ver_available}'
			'{lvcp_sub_inst_if_ver_installed}'
			'\033[0;32m     Link to PFL file list:\033[0m\t{cp_pfl}\n'
			'\033[0;32m     All matched files:\033[0m\t\t{path_all_str_hl}\n',
			lvcp_sub_aux_if_ver_available = 
			'\033[0;32m     Homepage:\033[0m\t\t\t{homepage}\n'
			'\033[0;32m     Description:\033[0m\t\t{description}\n'
			'\033[0;32m     Available versions:\033[0m\t{ver_available_str_hl}\n',
			lvcp_sub_inst_if_ver_installed = 
			'\033[0;32m     Installed versions:\033[0m\t{ver_installed_str_hl}\n',
			),
		e_file_allver = dict(
			lvcp = '{symbol} {c}/\033[1m{p}\033[0m\n'
			'{lvcp_sub_aux_if_ver_available}'
			'{lvcp_sub_inst_if_ver_installed}'
			'\033[0;32m     All matched versions:\033[0m\t{ver_all_str_hl}\n'
			'\n{lvver}',
			lvver = '\033[0;32m     File found in version:\033[0m\t{lvver_ver_hl}{lvver_symbol}\n'
			'\033[0;32m     Link to PFL file list of the version:\033[0m\t{lvver_ver_pfl}\n'
			'\033[0;32m     All matched files:\033[0m\t\t{path_all_str_hl}\n',
			sep_lvver = '\n',
			lvcp_sub_aux_if_ver_available = 
			'\033[0;32m     Homepage:\033[0m\t\t\t{homepage}\n'
			'\033[0;32m     Description:\033[0m\t\t{description}\n'
			'\033[0;32m     Available versions:\033[0m\t{ver_available_str_hl}\n',
			lvcp_sub_inst_if_ver_installed = 
			'\033[0;32m     Installed versions:\033[0m\t{ver_installed_str_hl}\n',
		),
		e_file_cptov = dict(
			lvcp = '{lvver}',
			lvver = '{lvver_ver_hl}\n',
		),
		e_file_cpvtof = dict(
			lvcp = '{lvver}',
			lvver = '{lvpath}',
			lvpath = '{lvpath_path_hl}\n',
		),
		full_uniq = dict(
			lvcp = '{symbol} {c}/\033[1m{p}\033[0m\n'
			'\033[0;32m     Homepage:\033[0m\t\t\t{homepage}\n'
			'\033[0;32m     Description:\033[0m\t\t{description}\n'
			'\033[0;32m     Link to PFL file list:\033[0m\t{cp_pfl}\n'
			'\033[0;32m     Available versions:\033[0m\t{ver_available_str_hl}\n'
			'\033[0;32m     Installed versions:\033[0m\t{ver_installed_str_hl}\n'
			'\033[0;32m     All matched files:\033[0m\t\t{path_all_str_hl}\n'
			'\n{lvver}',
			lvver = '{lvpath}',
			lvpath = '\033[0;32m     Matched file:\033[0m\t\t{lvpath_path_hl}\n'
			'\033[0;32m     File found with USE flag:\033[0m\t{lvpath_use_str}\n'
			'\033[0;32m     File found in arch:\033[0m\t{lvpath_arch_str}\n',
			sep_lvpath = '\n',
		),
		full_allver = dict(
			lvcp = '{symbol} {c}/\033[1m{p}\033[0m\n'
			'\033[0;32m     Homepage:\033[0m\t\t\t{homepage}\n'
			'\033[0;32m     Description:\033[0m\t\t{description}\n'
			'\033[0;32m     Link to PFL file list:\033[0m\t{cp_pfl}\n'
			'\033[0;32m     Available versions:\033[0m\t{ver_available_str_hl}\n'
			'\033[0;32m     Installed versions:\033[0m\t{ver_installed_str_hl}\n'
			'\n{lvver}',
			lvver = '\033[0;32m     File found in version:\033[0m\t{lvver_ver_hl}{lvver_symbol}\n'
			'\033[0;32m     All matched files:\033[0m\t\t{lvver_path_all_str_hl}\n'
			'\033[0;32m     Link to PFL file list of the version:\033[0m\t{lvver_ver_pfl}\n'
			'{lvpath}',
			sep_lvver = '\033[0;32m     -------------------\033[0m\n',
			lvpath = '\033[0;32m     Matched file:\033[0m\t\t{lvpath_path_hl}\n'
			'\033[0;32m     File exists locally?:\033[0m\t{lvpath_exists_str}\n'
			'\033[0;32m     File found with USE flag:\033[0m\t{lvpath_use_str}\n'
			'\033[0;32m     File found in arch:\033[0m\t{lvpath_arch_str}\n',
			sep_lvpath = '\n',
		),
		full_cptov = dict(
			lvcp = '{symbol} {c}/\033[1m{p}\033[0m\n'
			'\033[0;32m     Homepage:\033[0m\t\t\t{homepage}\n'
			'\033[0;32m     Description:\033[0m\t\t{description}\n'
			'\033[0;32m     Link to PFL file list:\033[0m\t{cp_pfl}\n'
			'\033[0;32m     Available versions:\033[0m\t{ver_available_str_hl}\n'
			'\033[0;32m     Installed versions:\033[0m\t{ver_installed_str_hl}\n'
			'\n{lvver}',
			lvver = '\033[0;32m     Version:\033[0m\t{lvver_ver_hl}{lvver_symbol}\n'
			'\033[0;32m     Link to PFL file list of the version:\033[0m\t{lvver_ver_pfl}\n'
			'{lvpath}',
			sep_lvver = '\n',
		),
		full_cpvtof = dict(
			lvcp = '{symbol} {c}/\033[1m{p}\033[0m\n'
			'\033[0;32m     Homepage:\033[0m\t\t\t{homepage}\n'
			'\033[0;32m     Description:\033[0m\t\t{description}\n'
			'\033[0;32m     Available versions:\033[0m\t{ver_available_str_hl}\n'
			'\033[0;32m     Installed versions:\033[0m\t{ver_installed_str_hl}\n'
			'\n{lvver}',
			lvver = '\033[0;32m     File found in version:\033[0m\t{lvver_ver_hl}{lvver_symbol}\n'
			'\033[0;32m     Link to PFL file list of the version:\033[0m\t{lvver_ver_pfl}\n'
			'\n{lvpath}',
			lvpath = '\033[0;32m     Matched file:\033[0m\t\t{lvpath_path_hl}\n'
			'\033[0;32m     File exists locally?:\033[0m\t{lvpath_exists_str}\n'
			'\033[0;32m     File found with USE flag:\033[0m\t{lvpath_use_str}\n'
			'\033[0;32m     File found in arch:\033[0m\t{lvpath_arch_str}\n',
			sep_lvpath = '\n',
		),
		raw_uniq = dict(
				lvcp = '{cp}\n',
				sep_lvcp = '',
		),
		raw_allver = dict(
				lvcp = '{lvver}',
				sep_lvcp = '',
				lvver = '{lvver_cpv}\n',
		),
		raw_cptov = dict(
			lvcp = '{lvver}',
			lvver = '{ver}\n',
		),
		raw_cpvtof = dict(
			lvcp = '{lvver}',
			lvver = '{lvpath}',
			lvpath = '{path}\n',
		),
)
conf = dict(
		debug = False,
		base_url = 'http://www.portagefilelist.de',
		minimal = False,
		source = 'pfl_html',
		loglevel = LOGLEVELS.warning,
		req_url = dict(
			pfl_html = dict(
				uniq = 'http://www.portagefilelist.de/site/query/file/?do',
				allver = 'http://www.portagefilelist.de/site/query/file/?do',
				cpvtof = 'http://www.portagefilelist.de/site/query/listPackageFiles/?category={c}&package={p}&version={v}&do',
				cptov = 'http://www.portagefilelist.de/site/query/listPackageVersions/?category={c}&package={p}&do',
				),
			pfl_json = dict(
				uniq = 'http://www.portagefilelist.de/site/query/robotFile?file={filename}&unique_packages',
				allver = 'http://www.portagefilelist.de/site/query/robotFile?file={filename}',
				cpvtof = 'http://www.portagefilelist.de/site/query/robotListPackageFiles?category={c}&package={p}&version={v}',
				cptov = 'http://www.portagefilelist.de/site/query/robotListPackageVersions?category={c}&package={p}'
				),
		),
		req_data = dict(
			pfl_html = dict(
				allver = dict(file = '{filename}'),
				uniq = dict(file = '{filename}', unique_packages = 'on'),
				cpvtof = None,
				cptov = None,
				),
			pfl_json = dict(
				allver = None,
				uniq = None,
				cpvtof = None,
				cptov = None,
				),
		),
)

# Global variables

system = sys_detect()
if 'gentoo' == system:
	db_port = portage.portdb
	db_installed = portage.db[portage.root]['vartree'].dbapi
vercmp_func = get_vercmp_func()

# Sort keys
def sort_key_tuple_first(path_group_tuple):
	return path_group_tuple[0]

def sort_key_ver_group(ver_group_tuple):
	return functools.cmp_to_key(vercmp_func)(ver_group_tuple[0])

sort_key_path_group = sort_key_cp_group = sort_key_tuple_first

sort_key_ver = functools.cmp_to_key(vercmp_func)

# Core functions

def read_result(source, mode, query):
	query['req_data'] = (urllib.parse.urlencode(
			{ key: value.format(**query) for key, value
			in conf['req_data'][source][mode].items() }).encode('iso8859-1')
			if conf['req_data'][source][mode] else None)
	query['req_url'] = conf['req_url'][source][mode].format(**query)
	req = urllib.request.Request(query['req_url'], query['req_data'],
			{ 'User-Agent': urllib.request.URLopener.version
			+ ' (e-file-py)', 'Accept-Encoding': 'gzip'})
	str_raw = ''
	report(LOGLEVELS.info, 'Sending request to the server...')
	report(LOGLEVELS.debug, repr([query['req_url'], query['req_data']]))
	with urllib.request.urlopen(req) as fraw:
		if 'gzip' == fraw.getheader('Content-Encoding'):
			fraw = gzip.GzipFile(fileobj = fraw, mode = 'rb')
		str_raw = fraw.read(10000000).decode('utf-8')
	if not str_raw:
		report(LOGLEVELS.fatal, "I got no data from the server!")
		str_raw = None
	report(LOGLEVELS.info, 'Result retrieved.')
	dbg_write('output.html', str_raw)
	return str_raw

def parse_result(source, mode, query, str_raw):
	def default_cp_get():
		return query['cp']

	def default_cp():
		pass

	def default_ver_get():
		return query['v']

	def default_ver():
		pass

	def default_path_get():
		return '/dev/null'

	def default_path():
		pass

	def ftocpv_cp_get():
		if 'pfl_html' == source:
			return ele_td_lst[0].get_text()
		elif 'pfl_json' == source:
			return jele['category'] + '/' + jele['package']

	def ftocpv_cp():
		v = ''
		if 'pfl_html' == source:
			v = conf['base_url'] + ele_td_lst[0].a['href']
		cp_group['cp_pfl'] = v
	
	def ftocpv_ver_get():
		if 'uniq' == mode:
			return ''
		elif 'allver' == mode:
			if 'pfl_html' == source:
				return ver_validate(ele_td_lst[4].get_text())
			elif 'pfl_json' == source:
				return ver_validate(jele['version'])

	def ftocpv_ver():
		v = ''
		if 'pfl_html' == source and 'allver' == mode:
			v = conf['base_url'] + ele_td_lst[4].a['href']
		ver_group['ver_pfl'] = v

	def ftocpv_path_get():
		if 'pfl_html' == source:
			return ele_td_lst[1].get_text()
		elif 'pfl_json' == source:
			return jele['path'] + '/' + jele['file']

	def ftocpv_path():
		if 'pfl_html' == source:
			path_group['type'] = commasplit(ele_td_lst[2].get_text())
			path_group['arch'] = commasplit(ele_td_lst[3].get_text())
			if 'uniq' == mode:
				path_group['use'] = commasplit(ele_td_lst[4].get_text())
			elif 'allver' == mode:
				path_group['use'] = commasplit(ele_td_lst[5].get_text())
		elif 'pfl_json' == source:
			path_group['type'] = jele.get('type', list())
			path_group['arch'] = jele.get('archs', list())
			path_group['use'] = jele.get('useflags', list())
	
	def cpvtof_ver():
		ver_group['ver_pfl'] = query['req_url']

	def cpvtof_path_get():
		if 'pfl_html' == source:
			return ele_td_lst[0].get_text()
		elif 'pfl_json' == source:
			return jele['path'] + '/' + jele['file']

	def cpvtof_path():
		if 'pfl_html' == source:
			path_group['type'] = commasplit(ele_td_lst[1].get_text())
			path_group['arch'] = commasplit(ele_td_lst[2].get_text())
			path_group['use'] = commasplit(ele_td_lst[3].get_text())
		elif 'pfl_json' == source:
			path_group['type'] = jele.get('type', list())
			path_group['arch'] = jele.get('archs', list())
			path_group['use'] = jele.get('useflags', list())

	def cptov_cp():
		if 'pfl_html' == source:
			cp_group['cp_pfl'] = query['req_url']
		return ''

	def cptov_ver_get():
		if 'pfl_html' == source:
			return ele_td_lst[0].get_text()
		elif 'pfl_json' == source:
			return jele['version']

	def cptov_ver():
		if 'pfl_html' == source:
			ver_group['ver_pfl'] = conf['base_url'] + ele_td_lst[0].a['href']
		return ''

	def parse_ele():
		nonlocal cp_group, ver_group, path_group
		cp = parse_func['cp_get']()
		if cp not in result:
			result[cp] = dict()
			cp_group = result[cp]
			cp_group['ver_groups'] = dict()
			cp_group['c'], cp_group['p'] = cp.split('/', 1)
			parse_func['cp']()
		cp_group = result[cp]
		ver = parse_func['ver_get']()
		if ver not in cp_group['ver_groups']:
			cp_group['ver_groups'][ver] = dict()
			ver_group = cp_group['ver_groups'][ver]
			ver_group['path_groups'] = dict()
			ver_group['cpv'] = cp + '-' + ver
			parse_func['ver']()
		ver_group = cp_group['ver_groups'][ver]
		path = parse_func['path_get']()
		if path not in ver_group['path_groups']:
			ver_group['path_groups'][path] = dict()
			path_group = ver_group['path_groups'][path]
			parse_func['path']()

	result = dict()
	parse_func = dict()
	cp_group = ver_group = path_group = None
	if mode in ('uniq', 'allver'):
		prefix = 'ftocpv_'
	else:
		prefix = mode + '_'
	for i in ('cp', 'ver', 'path'):
		for j in ('', '_get'):
			parse_func[i + j] = locals().get(prefix + i + j,
					locals()['default_' + i + j])
	if 'pfl_html' == source:
		import bs4
		soup = bs4.BeautifulSoup(str_raw, 'html')
		ele_a_result = soup.find('a', id = 'result')
		if not ele_a_result:
			pass
		ele_table = [ ele for ele in ele_a_result.next_siblings
				if isinstance(ele, bs4.element.Tag)
				and 'table' == ele.name.lower() ]
		if not ele_table:
			pass
		ele_table = ele_table[0]
		for ele_tr in ele_table.children:
			if not (isinstance(ele_tr, bs4.element.Tag)
					and 'tr' == ele_tr.name.lower()):
				continue
			ele_td_lst = ele_tr.find_all('td')
			if not ele_td_lst:
				continue
			if 'colspan' in ele_td_lst[0].attrs:
				# No results found
				break
			parse_ele()
	elif 'pfl_json' == source:
		import json
		jsonout = json.loads(str_raw)
		if isinstance(jsonout.get('error'), dict) \
				and jsonout['error'].get('code'):
			report(LOGLEVELS.fatal, 'Server failure: '
					+ repr(jsonout['error'].get('code')) + ': '
					+ repr(jsonout['error'].get('message')))
		if isinstance(jsonout.get('result'), list):
			for jele in jsonout['result']:
				parse_ele()
	return result

def extra_info(mode, query, cp, cp_group):
	# Get cp-specific information
	cp_group['exists'] = False
	cp_group['installed_flag'] = ''
	if 'gentoo' == system:
		p_installed = db_installed.match(cp)
		cp_group['ver_installed'] = plist_getver(p_installed)
		p_available = db_port.match(cp)
		cp_group['ver_available'] = plist_getver(p_available)
		cp_group['ver_installed'].sort(key = sort_key_ver)
		cp_group['ver_available'].sort(key = sort_key_ver)
		if p_available:
			extra_metadata = db_port.aux_get(p_available[-1],
					[ 'HOMEPAGE', 'DESCRIPTION' ])
			cp_group['homepage'] = extra_metadata[0]
			cp_group['description'] = extra_metadata[1]
	# Fill empty properties
	for i in { 'homepage', 'description' }:
		if i not in cp_group:
			cp_group[i] = ''
	for i in { 'ver_installed', 'ver_available' }:
		if i not in cp_group:
			cp_group[i] = list()
	for ver, ver_group in cp_group['ver_groups'].items():
		ver_group['exists'] = False
		# Get path-specific information
		for path, path_group in ver_group['path_groups'].items():
			path_group['exists'] = os.path.exists(path)
			if path_group['exists']:
				ver_group['exists'] = True
		if ver_group['exists']:
			cp_group['exists'] = True
		# Get ver-specific information
		ver_group['installed_flag'] = ''
		if 'gentoo' != system or not cp_group['ver_installed']:
			continue
		if ver:
			if ver in cp_group['ver_installed']:
				ver_group['installed_flag'] = 'installed'
				cp_group['installed_flag'] = 'installed'
			else:
				if vercmp_func(ver,
						cp_group['ver_installed'][-1]) > 0:
					ver_group['installed_flag'] = 'upgrade'
					if '' == cp_group['installed_flag']:
						cp_group['installed_flag'] = 'upgrade'
				else:
					ver_group['installed_flag'] = 'downgrade'
					if 'installed' != cp_group['installed_flag']:
						cp_group['installed_flag'] = 'downgrade'
		else:
			ver_group['installed_flag'] = 'installed'
			cp_group['installed_flag'] = 'installed'
	report(LOGLEVELS.debug, 'cp_group = ' + repr(cp_group))
	return cp_group

def filter_result(result, filters):
	def chkgentoo(filter_name):
		if 'gentoo' != system:
			report(LOGLEVELS.warning, 'filter {} is not available for non-Gentoo'
					' systems. Filter ignored.'.format(filter_name))
			return False
		else:
			return True
	
	# cp-level filters
	rmlst_cp = set()
	if 'available' in filters and chkgentoo('available'):
		for cp, cp_group in result.items():
			if not cp_group['ver_available']:
				rmlst_cp.add(cp)
	if 'installed' in filters and chkgentoo('installed'):
		for cp, cp_group in result.items():
			if not cp_group['installed_flag']:
				rmlst_cp.add(cp)
	for cp in rmlst_cp:
		del result[cp]
	# TODO: Implement more filters here
	return result

def sort_result(result):
	for cp, cp_group in result.items():
		for ver, ver_group in cp_group['ver_groups'].items():
			ver_group['path_groups'] = \
					sorted(ver_group['path_groups'].items(),
					key = sort_key_path_group)
		cp_group['ver_groups'] = \
				sorted(cp_group['ver_groups'].items(),
				key = sort_key_ver_group)
	result = sorted(result.items(),
			key = sort_key_cp_group)
	return result

def output_preprocess(cp, cp_group, fmtstr):
	def str_hl(string, dec_id):
		return (fmtstr['prefix_' + dec_id] + string +
				fmtstr['suffix_' + dec_id])
	
	def lst_to_str(lst, sep, match, dec_id):
		newlst = [ (str_hl(item, dec_id) if item in match else item)
				for item in lst ]
		return sep.join(newlst)

	def lst_to_str_double(lst, sep, match, dec_id, match2, dec_id2):
		newlst = [ (str_hl(item, dec_id) if item in match else 
				(str_hl(item, dec_id2) if item in match2 else item))
				for item in lst ]
		return sep.join(newlst)

	def repr_bool(val, dec_id):
		if val:
			return fmtstr['repr_true_' + dec_id]
		else:
			return fmtstr['repr_false_' + dec_id]

	def repr_empty_str(val, dec_id):
		if val:
			return val
		else:
			return fmtstr['repr_empty_' + dec_id]
	
	def ver_hl(string, ver, cp_group, ver_group):
		if ver:
			if 'installed' == ver_group['installed_flag']:
				string = str_hl(string, 'installed')
			elif ver in cp_group['ver_available']:
				string = str_hl(string, 'available')
		else:
			string = repr_empty_str(string, 'ver')
		return string

	cp_group['path_all'] = set()
	cp_group['path_all_exists'] = set()
	cp_group['ver_all'] = set()
	for ver, ver_group in cp_group['ver_groups']:
		ver_group['path_all'] = set()
		ver_group['path_all_exists'] = set()
		for path, path_group in ver_group['path_groups']:
			path_group['type_str'] = \
					fmtstr['sep'].join(path_group.get('type', ''))
			path_group['arch_str'] = \
					fmtstr['sep'].join(path_group.get('arch', ''))
			path_group['use_str'] = \
					fmtstr['sep'].join(path_group.get('use', ''))
			ver_group['path_all'].add(path)
			path_group['exists_str'] = repr_bool(path_group['exists'],
					'exists')
			if path_group['exists']:
				path_group['path_hl'] = str_hl(path, 'exists')
				ver_group['path_all_exists'].add(path)
			else:
				path_group['path_hl'] = path
		ver_group['ver_hl'] = ver_hl(ver, ver, cp_group, ver_group)
		ver_group['cpv_hl'] = ver_hl(ver_group['cpv'], ver, cp_group, 
				ver_group)
		ver_group['exists_str'] = repr_bool(ver_group['exists'], 'exists')
		ver_group['symbol'] = fmtstr \
				['sym_' + ver_group['installed_flag']]
		ver_group['path_all_str'] = \
				fmtstr['sep'].join(ver_group['path_all'])
		ver_group['path_all_str_hl'] = lst_to_str(ver_group['path_all'],
			fmtstr['sep'], ver_group['path_all_exists'], 'exists')
		cp_group['path_all'] |= ver_group['path_all']
		cp_group['path_all_exists'] |= ver_group['path_all_exists']
		cp_group['ver_all'].add(ver)
		ver_group['path_all'] = sorted(ver_group['path_all'])
		ver_group['path_all_exists'] = sorted(ver_group['path_all_exists'])
	cp_group['path_all'] = sorted(cp_group['path_all'])
	cp_group['path_all_exists'] = sorted(cp_group['path_all_exists'])
	cp_group['ver_all'] = sorted(cp_group['ver_all'], key = sort_key_ver)
	cp_group['exists_str'] = repr_bool(cp_group['exists'], 'exists')
	cp_group['path_all_str'] = \
				fmtstr['sep'].join(cp_group['path_all'])
	cp_group['path_all_str_hl'] = lst_to_str(cp_group['path_all'],
			fmtstr['sep'], cp_group['path_all_exists'], 'exists')
	cp_group['ver_all_str'] = repr_empty_str(
			fmtstr['sep'].join(cp_group['ver_all']), 'ver_all')
	cp_group['ver_all_str_hl'] = repr_empty_str(lst_to_str_double(
			cp_group['ver_all'], fmtstr['sep'], cp_group['ver_installed'],
			'installed', cp_group['ver_available'], 'available'), 'ver_all')
	cp_group['ver_available_str'] = \
			fmtstr['sep'].join(cp_group['ver_available'])
	cp_group['ver_available_str_hl'] = repr_empty_str(lst_to_str_double(
			cp_group['ver_available'], fmtstr['sep'],
			cp_group['ver_installed'], 'installed',
			cp_group['ver_all'], 'matched'), 'ver_available')
	cp_group['ver_installed_str'] = \
			fmtstr['sep'].join(cp_group['ver_installed'])
	cp_group['ver_installed_str_hl'] = repr_empty_str(fmtstr['sep'].join(
			[ str_hl(ver, 'installed') for ver
			in cp_group['ver_installed'] ]), 'ver_installed')
	cp_group['symbol'] = fmtstr['sym_' + cp_group['installed_flag']]

def print_result(mode, query, result, fmtstr):
	def ifsearch(key, kwargs):
		pos = key.find('_if_not_')
		if -1 != pos:
			return not bool(kwargs[key[pos + len('_if_not_'):]])
		pos = key.find('_if_')
		if -1 != pos:
			return bool(kwargs[key[pos + len('_if_'):]])
		return True

	cp_count = len(result)
	if not cp_count:
		print(fmtstr['noresult'], end = '')
		return 1
	lvpath_subs = [ key for key in fmtstr if key.startswith('lvpath_sub_') ]
	lvver_subs = [ key for key in fmtstr if key.startswith('lvver_sub_') ]
	lvcp_subs = [ key for key in fmtstr if key.startswith('lvcp_sub_') ]
	strdct_lvver = { key: '' for key in lvver_subs }
	strdct_lvver['lvver'] = ''
	strdct_lvpath = { key: '' for key in lvpath_subs }
	strdct_lvpath['lvpath'] = ''
	for cp, cp_group in result:
		cp_kwargs = query.copy()
		cp_kwargs.update(cp_group)
		del cp_kwargs['ver_groups']
		cp_kwargs['cp'] = cp
		for key in strdct_lvver:
			strdct_lvver[key] = ''
		ver_count = len(cp_group['ver_groups'])
		for ver, ver_group in cp_group['ver_groups']:
			ver_kwargs = { 'lvver_' + key: value for key, value
					in ver_group.items() if 'path_groups' != key }
			ver_kwargs.update(cp_kwargs)
			ver_kwargs['ver'] = ver
			for key in strdct_lvpath:
				strdct_lvpath[key] = ''
			path_count = len(ver_group['path_groups'])
			for path, path_group in ver_group['path_groups']:
				path_kwargs = { 'lvpath_' + key: value for key, value
						in path_group.items() if 'path_groups' != key }
				path_kwargs.update(ver_kwargs)
				path_kwargs['path'] = path
				strdct_cur = dict()
				for key in lvpath_subs:
					if ifsearch(key, path_kwargs):
						strdct_cur[key] = fmtstr[key].format(**path_kwargs)
					else:
						strdct_cur[key] = ''
					path_kwargs[key] = strdct_cur[key]
					strdct_lvpath[key] += strdct_cur[key]
				strdct_lvpath['lvpath'] += \
						fmtstr['lvpath'].format(**path_kwargs)
				path_count -= 1
				if path_count:
					for key in strdct_lvpath:
						strdct_lvpath[key] += fmtstr.get('sep_' + key, '')
			ver_kwargs.update(strdct_lvpath)
			strdct_cur = dict()
			for key in lvver_subs:
				if ifsearch(key, ver_kwargs):
					strdct_cur[key] = fmtstr[key].format(**ver_kwargs)
				else:
					strdct_cur[key] = ''
				ver_kwargs[key] = strdct_cur[key]
				strdct_lvver[key] += strdct_cur[key]
			strdct_lvver['lvver'] += \
					fmtstr['lvver'].format(**ver_kwargs)
			ver_count -= 1
			if ver_count:
				for key in strdct_lvver:
					strdct_lvver[key] += fmtstr.get('sep_' + key, '')
		cp_kwargs.update(strdct_lvver)
		for key in lvcp_subs:
			if ifsearch(key, cp_kwargs):
				cp_kwargs[key] = fmtstr[key].format(**cp_kwargs)
			else:
				cp_kwargs[key] = ''
		lvcp_str = fmtstr['lvcp'].format(**cp_kwargs)
		cp_count -= 1
		if cp_count:
			lvcp_str += fmtstr['sep_lvcp']
		print(lvcp_str, end = '')
	return 0

# Argument parsing
parser = argparse.ArgumentParser(description='Python clone of e-file, searching Gentoo package names with database from portagefilelist.de')
parser.add_argument('query', nargs = '+', help = 'the query. '
		'format for normal mode and -U mode is "filename"; '
		'acceptable formats for -l mode are "category/packagename-version", "category/packagename version", "packagename-version", "packagename version" or "category packagename version"; '
		'formats for -L mode are "category/packagename", "category packagename" or "packagename"'
		)
parser.add_argument('-d', '--debug', action = 'store_true', 
		help = 'enable debugging mode')
parser.add_argument('--source', choices = SOURCES, 
		help = 'specify info source')
parser.add_argument('--loglevel', choices = LOGLEVELS_STRS, 
		help = 'specify output verbosity')
parser.add_argument('-m', '--minimal', action = 'store_true', 
		help = 'do not calculate extra proprieties, '
		'to save time for some specific usages')
parser_modes = parser.add_mutually_exclusive_group()
parser_modes.add_argument('-U', '--no-unique', action = 'store_const',
		dest = 'mode', const = 'allver', default = 'uniq',
		help = 'search for all package versions')
parser_modes.add_argument('-l', '--list-files', action = 'store_const',
		dest = 'mode', const = 'cpvtof',
		help = 'search for contents of a package-version')
parser_modes.add_argument('-L', '--list-versions', action = 'store_const',
		dest = 'mode', const = 'cptov',
		help = 'search for all versions of a package with a record on PFL')
parser_filters = parser.add_argument_group('filters',
		"Note that some filters don't work on non-Gentoo systems.")
parser_filters.add_argument('--available', action = 'append_const',
		dest = 'filters', const = 'available', default = [],
		help = "don't display packages that are not available locally")
parser_filters.add_argument('--installed', action = 'append_const', 
		dest = 'filters', const = 'installed',
		help = "don't display packages that are not installed")
parser_fmtstr = parser.add_argument_group('format strings',
		"TODO: ...")
parser_fmtstr.add_argument('--format', nargs = '*', default = [],
		metavar = 'KEY:VALUE', help = 'specify a particular item KEY '
		'as VALUE in format strings')
parser_fmtstr.add_argument('--fmtstrset',
		choices = [ key for key in PREDEF_FMTSTR.keys()
		if 'base' != key ], help = 'choose a predefined format string set, '
		'values ending with "_allver" are only usable for -U mode, '
		'values ending with "_uniq" usually should be used without -U, '
		'values ending with "_cpvtof" should be used with -l, '
		'values ending with "_cptov" should be used with -L, ')

args = parser.parse_args()

if args.debug:
	conf['debug'] = True
	conf['loglevel'] = LOGLEVELS.debug
if args.loglevel:
	conf['loglevel'] = getattr(LOGLEVELS, args.loglevel)
report(LOGLEVELS.debug, 'args = ' + repr(args))
if args.source:
	conf['source'] = args.source
conf['minimal'] = args.minimal

mode = args.mode

# Query processing
query = dict()
if 'cpvtof' == mode:
	query['c'], query['p'], query['v'] = process_args_cpv(args.query)
	query['cp'] = query['c'] + '/' + query['p']
	query['cpv'] = query['cp'] + '-' + query['v']
elif 'cptov' == mode:
	query['c'], query['p'] = process_args_cp(args.query)
	query['cp'] = query['c'] + '/' + query['p']
else:
	if 1 < len(args.query):
		report(LOGLEVELS.warning, 'I see too many arguments.')
	query['filename'] = args.query[0]

# Format string processing
# Use e-file format strings as default temporarily
fmtstr = 'e_file_' + mode
# e-file compatibility
if 'e-file' == os.path.basename(sys.argv[0]):
	fmtstr = 'e_file_' + mode
# --fmtstrset handling
if args.fmtstrset:
	fmtstr = args.fmtstrset
conf['fmtstr'] = PREDEF_FMTSTR[fmtstr]
# --format handling
for item in args.format:
	key, value = item.split(':', 1)
	conf['fmtstr'][key] = value
# Copy format string set
for key, value in PREDEF_FMTSTR['base'].items():
	if key not in conf['fmtstr']:
		conf['fmtstr'][key] = value
del PREDEF_FMTSTR

result = read_result(conf['source'], mode, query)
# result = open('/tmp/output.html', 'r').read()
result = parse_result(conf['source'], mode, query, result)
if not result:
	quit(0)
if not conf['minimal']:
	for cp, cp_group in result.items():
		extra_info(mode, query, cp, cp_group)
result = sort_result(filter_result(result, args.filters))
if not conf['minimal']:
	for cp, cp_group in result:
		output_preprocess(cp, cp_group, conf['fmtstr'])
quit(print_result(mode, query, result, conf['fmtstr']))
