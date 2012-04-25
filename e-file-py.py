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

def info_sort_key(info):
	return portage.versions.cpv_sort_key()(info['cp'] + '-' +
			(info['ver'] if info['ver'] else '1'))

def info_sort_key_raw(info):
	return (info['cp'] + '-' + (info['ver'] if info['ver'] else '1'))

# Default configurations

LOGLEVELS = ( 'fatal', 'info', 'debug' )

conf = dict(
		debug = False,
		separator = ', ',
		base_url = 'http://www.portagefilelist.de',
		system = sys_detect(),
		minimal = False,
		loglevel = 'fatal',
		fmtstr = '{symbol} {c}/\033[1m{p}\033[0m\n'
			'\033[0;32m     Matched file:\033[0m\t\t{path}\n'
			'\033[0;32m     File exists locally?:\033[0m\t{exists}\n'
			'\033[0;32m     Link to PFL file list:\033[0m\t{cp_pfl}\n'
			'\033[0;32m     Link to PFL file list of the version:\033[0m\t{ver_pfl}\n'
			'\033[0;32m     File found with USE flag:\033[0m\t{use_str}\n'
			'\033[0;32m     File found in version:\033[0m\t{ver}\n'
			'\033[0;32m     File found in arch:\033[0m\t{arch_str}\n'
			'\033[0;32m     Available versions:'
			'\033[0m\t{ver_available_str}\n'
			'\033[0;32m     Installed versions:'
			'\033[0m\t{ver_installed_str}\n'
			'\033[0;32m     Homepage:\033[0m\t\t\t{homepage}\n'
			'\033[0;32m     Description:\033[0m\t\t{description}\n\n',
		sym_plain = ' * ',
		sym_installed = '[I]',
		sym_upgrade = '[U]',
		sym_downgrade = '[D]', 
		req_url = 'http://www.portagefilelist.de/site/query/file/?do',
		req_data = dict(allver = dict(file = '{filename}'),
			uniq = dict(file = '{filename}', unique_packages = 'on'))
)

# Global variables

info_cache = dict()
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
	result = list()
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
		info = dict()
		info['cp'] = ele_td_lst[0].get_text()
		info['c'], info['p'] = info['cp'].split('/')
		info['cp_pfl'] = conf['base_url'] + ele_td_lst[0].a['href']
		info['path'] = ele_td_lst[1].get_text()
		info['type'] = commasplit(ele_td_lst[2].get_text())
		info['arch'] = commasplit(ele_td_lst[3].get_text())
		if 'uniq' == mode:
			info['ver'] = ''
			info['use'] = commasplit(ele_td_lst[4].get_text())
			info['ver_pfl'] = ''
		elif 'allver' == mode:
			info['ver'] = ele_td_lst[4].get_text()
			# Ugly hack to deal with some broken package versions
			# PFL reports
			if '.' == info['ver'][-1]:
				info['ver'] = info['ver'][:-1]
			info['ver_pfl'] = conf['base_url'] + ele_td_lst[4].a['href']
			info['use'] = commasplit(ele_td_lst[5].get_text())
		report('debug', 'info = ' + repr(info))
		result.append(info)
	return result

def extra_info(info):
	info['exists'] = os.path.exists(info['path'])
	# Gentoo-specific information, using Portage API
	if 'gentoo' == conf['system']:
		if info['cp'] not in info_cache:
			info_cache[info['cp']] = dict()
			cur_cache = info_cache[info['cp']]
			# Fill info into cache
			p_installed = db_installed.match(info['cp'])
			cur_cache['ver_installed'] = plist_getver(p_installed)
			p_available = db_port.match(info['cp'])
			cur_cache['ver_available'] = plist_getver(p_available)
			if p_available:
				extra_metadata = db_port.aux_get(p_available[-1],
						[ 'HOMEPAGE', 'DESCRIPTION' ])
				cur_cache['homepage'] = extra_metadata[0]
				cur_cache['description'] = extra_metadata[1]
			else:
				cur_cache['homepage'] = ''
				cur_cache['description'] = ''
		cur_cache = info_cache[info['cp']]
		# Copy info from cache
		for i in { 'ver_installed', 'ver_available', 'homepage',
				'description' }:
			info[i] = cur_cache[i]
		if info['ver']:
			info['installed'] = repr(info['ver'] in info['ver_installed'])
		else:
			info['installed'] = repr(bool(info['ver_installed']))
		# Ugly way to test if a package is installed
		# pv_installed = glob.glob(conf['dir_pkgdb'] + info['pv'] + '-[0-9]*')
	else:
		# Fill empty attributes
		for i in { 'installed', 'homepage', 'description' }:
			if i not in info:
				info[i] = ''
		for i in { 'ver_installed', 'ver_available' }:
			if i not in info:
				info[i] = list()
	report('debug', 'info = ' + repr(info))
	return info

def filter_result(result):
	# TODO: Implement filters here
	return result

def sort_result(result):
	if 'gentoo' == conf['system']:
		result.sort(key = info_sort_key)
	else:
		result.sort(key = info_sort_key_raw)
	if 'gentoo' == conf['system']:
		for i in result:
			i['ver_installed'].sort(key = functools.cmp_to_key(
					portage.versions.vercmp))
			i['ver_available'].sort(key = functools.cmp_to_key(
					portage.versions.vercmp))
	else:
		for i in result:
			i['ver_installed'].sort()
			i['ver_available'].sort()
	return result

def print_result(mode, info, fmtstr):
	info['type_str'] = conf['separator'].join(info['type'])
	info['arch_str'] = conf['separator'].join(info['arch'])
	info['use_str'] = conf['separator'].join(info['use'])
	info['ver_available_str'] = \
			conf['separator'].join(info['ver_available'])
	info['ver_installed_str'] = \
			conf['separator'].join(info['ver_installed'])
	info['symbol'] = conf['sym_plain']
	if info['ver_installed']:
		info['symbol'] = conf['sym_installed']
		if info['ver'] and info['ver'] not in info['ver_installed']:
			if 'gentoo' == conf['system']:
				info['symbol'] = (conf['sym_upgrade'] if 
						portage.versions.vercmp(info['ver'],
						info['ver_installed'][-1]) > 0
						else conf['sym_downgrade'])
			else:
				info['symbol'] = (conf['sym_upgrade'] if 
						info['ver'] > 
						info['ver_installed'][-1]
						else conf['sym_downgrade'])
	print(fmtstr.format(**info), end = '')

# Argument parsing
parser = argparse.ArgumentParser(description='Python clone of e-file, searching Gentoo package names with database from portagefilelist.de')
parser.add_argument('filename', help = 'the filename to search')
parser.add_argument('-d', '--debug', action = 'store_true', 
		help='enable debugging mode')
parser.add_argument('--format', default = conf['fmtstr'], 
		help='format string')
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
conf['fmtstr'] = args.format
conf['minimal'] = args.minimal
if args.no_unique:
	mode = 'allver'
else:
	mode = 'uniq'

result = parse_result(mode, read_result(mode, args.filename))
if not conf['minimal']:
	for i in result:
		extra_info(i)
result = sort_result(filter_result(result))
for i in result:
	print_result(mode, i, conf['fmtstr'])
