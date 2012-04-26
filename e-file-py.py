#! /usr/bin/env python3.2

import urllib.request, urllib.parse, bs4, argparse, sys, os, functools
try:
	import portage
except ImportError:
	pass

# Helper functions

def report(level, msg):
	if 'fatal' == level:
		msg = 'FATAL: ' + msg
	elif 'info' == level:
		msg = 'INFO: ' + msg
	elif 'debug' == level:
		msg = 'DEBUG: ' + msg
	if LOGLEVELS.index(conf['loglevel']) >= LOGLEVELS.index(level):
		print(msg, file = sys.stderr)
	if 'fatal' == level:
		quit()
	return 0

def dbg_write(id, content):
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

def vercmp_func():
	if 'gentoo' == conf['system']:
		return portage.versions.vercmp
	else:
		return (lambda a, b: (a > b) - 0.5)

def ver_validate(ver):
	# Ugly hack to deal with some broken package versions
	# PFL reports
	if '.' == ver[-1]:
		ver = ver[:-1]
	if 'gentoo' == conf['system'] and not portage.versions.ververify(ver):
		report('warning', 'Invalid version number: {}'.format(ver))
		ver = '0'
	return ver

# Default configurations

LOGLEVELS = ( 'fatal', 'warning', 'info', 'debug' )

conf = dict(
		debug = False,
		separator = ', ',
		base_url = 'http://www.portagefilelist.de',
		system = sys_detect(),
		minimal = False,
		loglevel = 'warning',
		fmtstr = dict(
			lvcp = '{symbol} {c}/\033[1m{p}\033[0m\n'
			'\033[0;32m     Homepage:\033[0m\t\t\t{homepage}\n'
			'\033[0;32m     Description:\033[0m\t\t{description}\n'
			'\033[0;32m     Available versions:\033[0m\t{ver_available_str}\n'
			'\033[0;32m     Installed versions:\033[0m\t{ver_installed_str}\n'
			'{lvver}',
			lvcp_sep = '\n',
			lvver = '\033[0;32m     File found in version:\033[0m\t{ver}{lvver_symbol}\n'
			'\033[0;32m     Link to PFL file list of the version:\033[0m\t{lvver_ver_pfl}\n'
			'{lvpath}',
			lvver_sep = '\033[0;32m     -------------------\033[0m\n',
			lvpath = '\033[0;32m     Matched file:\033[0m\t\t{path}\n'
			'\033[0;32m     File exists locally?:\033[0m\t{lvpath_exists}\n'
			'\033[0;32m     Link to PFL file list:\033[0m\t{cp_pfl}\n'
			'\033[0;32m     File found with USE flag:\033[0m\t{lvpath_use_str}\n'
			'\033[0;32m     File found in arch:\033[0m\t{lvpath_arch_str}\n',
			lvpath_sep = '\n'),
		sym_ = ' * ',
		sym_installed = '[I]',
		sym_upgrade = '[U]',
		sym_downgrade = '[D]', 
		req_url = 'http://www.portagefilelist.de/site/query/file/?do',
		req_data = dict(allver = dict(file = '{filename}'),
			uniq = dict(file = '{filename}', unique_packages = 'on'))
)
conf['vercmp_func'] = vercmp_func()

# Sort keys
def sort_key_tuple_first(path_group_tuple):
	return path_group_tuple[0]

def sort_key_ver_group(ver_group_tuple):
	return functools.cmp_to_key(conf['vercmp_func'])(ver_group_tuple[0])

sort_key_path_group = sort_key_cp_group = sort_key_tuple_first

sort_key_ver = functools.cmp_to_key(conf['vercmp_func'])

# Global variables

if 'gentoo' == conf['system']:
	db_port = portage.portdb
	db_installed = portage.db[portage.root]['vartree'].dbapi

# Core functions

def read_result(mode, filename):
	req_data = dict()
	req_data = urllib.parse.urlencode(
			{ key: value.format(filename = filename) for key, value
			in conf['req_data'][mode].items() }).encode('iso8859-1')
	report('debug', 'req_data = ' + repr(req_data))
	req = urllib.request.Request(conf['req_url'], req_data,
			{ 'User-Agent': urllib.request.URLopener.version
			+ ' (e-file-py)' })
	str_raw = ''
	report('info', 'Sending request to the server...')
	with urllib.request.urlopen(req) as fraw:
		str_raw = fraw.read(10000000).decode('utf-8')
	if not str_raw:
		report_error('fatal', "I got no data from the server!")
		str_raw = None
	report('info', 'Result retrieved.')
	dbg_write('output.html', str_raw)
	return str_raw

def parse_result(mode, str_raw):
	result = dict()
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
		# Handling cp-specific properties
		cp = ele_td_lst[0].get_text()
		if cp not in result:
			result[cp] = dict()
			cp_group = result[cp]
			cp_group['ver_groups'] = dict()
			cp_group['c'], cp_group['p'] = cp.split('/')
			cp_group['cp_pfl'] = conf['base_url'] + ele_td_lst[0].a['href']
		cp_group = result[cp]
		# Handling version-specific properties
		if 'uniq' == mode:
			ver = ''
		elif 'allver' == mode:
			ver = ver_validate(ele_td_lst[4].get_text())
		if ver not in cp_group['ver_groups']:
			cp_group['ver_groups'][ver] = dict()
			ver_group = cp_group['ver_groups'][ver]
			ver_group['path_groups'] = dict()
			if 'uniq' == mode:
				ver_group['ver_pfl'] = ''
			elif 'allver' == mode:
				ver_group['ver_pfl'] = conf['base_url'] \
						+ ele_td_lst[4].a['href']
		ver_group = cp_group['ver_groups'][ver]
		# Handling path-specific properties
		path = ele_td_lst[1].get_text()
		if path not in ver_group['path_groups']:
			ver_group['path_groups'][path] = dict()
			path_group = ver_group['path_groups'][path]
			path_group['type'] = commasplit(ele_td_lst[2].get_text())
			path_group['arch'] = commasplit(ele_td_lst[3].get_text())
			if 'uniq' == mode:
				path_group['use'] = commasplit(ele_td_lst[4].get_text())
			elif 'allver' == mode:
				path_group['use'] = commasplit(ele_td_lst[5].get_text())
		report('debug', 'info = ' + repr(cp_group))
	return result

def extra_info(cp, cp_group):
	# Get cp-specific information
	cp_group['exists'] = False
	cp_group['installed_flag'] = ''
	if 'gentoo' == conf['system']:
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
		if 'gentoo' != conf['system'] or not cp_group['ver_installed']:
			continue
		if ver:
			if ver in cp_group['ver_installed']:
				ver_group['installed_flag'] = 'installed'
				cp_group['installed_flag'] = 'installed'
			else:
				if conf['vercmp_func'](ver,
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
	report('debug', 'cp_group = ' + repr(cp_group))
	return cp_group

def filter_result(result):
	# TODO: Implement filters here
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

def output_preprocess(cp, cp_group):
	for ver, ver_group in cp_group['ver_groups']:
		for path, path_group in ver_group['path_groups']:
			path_group['type_str'] = \
					conf['separator'].join(path_group['type'])
			path_group['arch_str'] = \
					conf['separator'].join(path_group['arch'])
			path_group['use_str'] = \
					conf['separator'].join(path_group['use'])
		ver_group['symbol'] = conf['sym_' + ver_group['installed_flag']]
	cp_group['ver_available_str'] = \
			conf['separator'].join(cp_group['ver_available'])
	cp_group['ver_installed_str'] = \
			conf['separator'].join(cp_group['ver_installed'])
	cp_group['symbol'] = conf['sym_' + cp_group['installed_flag']]

def print_result(mode, result, fmtstr):
	cp_count = len(result)
	for cp, cp_group in result:
		cp_kwargs = cp_group.copy()
		del cp_kwargs['ver_groups']
		lvver_str = ''
		ver_count = len(cp_group['ver_groups'])
		for ver, ver_group in cp_group['ver_groups']:
			ver_kwargs = { 'lvver_' + key: value for key, value
					in ver_group.items() if 'path_groups' != key }
			ver_kwargs.update(cp_kwargs)
			ver_kwargs['ver'] = ver
			lvpath_str = ''
			path_count = len(ver_group['path_groups'])
			for path, path_group in ver_group['path_groups']:
				path_kwargs = { 'lvpath_' + key: value for key, value
						in path_group.items() if 'path_groups' != key }
				path_kwargs.update(ver_kwargs)
				path_kwargs['path'] = path
				lvpath_str += fmtstr['lvpath'].format(**path_kwargs)
				path_count -= 1
				if path_count:
					lvpath_str += fmtstr['lvpath_sep']
			lvver_str += fmtstr['lvver'].format(lvpath = lvpath_str,
					**ver_kwargs)
			ver_count -= 1
			if ver_count:
				lvver_str += fmtstr['lvver_sep']
		lvcp_str = fmtstr['lvcp'].format(lvver = lvver_str, **cp_kwargs)
		cp_count -= 1
		if cp_count:
			lvcp_str += fmtstr['lvcp_sep']
		print(lvcp_str, end = '')

# Argument parsing
parser = argparse.ArgumentParser(description='Python clone of e-file, searching Gentoo package names with database from portagefilelist.de')
parser.add_argument('filename', help = 'the filename to search')
parser.add_argument('-d', '--debug', action = 'store_true', 
		help='enable debugging mode')
# parser.add_argument('--format', 
# 		help='format string')
parser.add_argument('--loglevel',
		help='specify output verbosity')
parser.add_argument('-m', '--minimal', action = 'store_true', 
		help = 'do not cacalcuate extra properities, '
		'to save time for some specific usages')
parser.add_argument('-U', '--no-unique', action = 'store_true',
		help = 'search for all package versions')

args = parser.parse_args()
report('debug', 'args = ' + repr(args))

if args.debug:
	conf['debug'] = True
	conf['loglevel'] = 'debug'
if args.loglevel and args.loglevel in LOGLEVELS:
	conf['loglevel'] = args.loglevel
# conf['fmtstr'] = args.format
conf['minimal'] = args.minimal
if args.no_unique:
	mode = 'allver'
else:
	mode = 'uniq'

result = read_result(mode, args.filename)
# result = open('/tmp/output.html', 'r').read()
result = parse_result(mode, result)
if not conf['minimal']:
	for cp, cp_group in result.items():
		extra_info(cp, cp_group)
result = sort_result(filter_result(result))
for cp, cp_group in result:
	output_preprocess(cp, cp_group)
print_result(mode, result, conf['fmtstr'])
