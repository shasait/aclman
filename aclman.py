#!/usr/bin/python3
# -*- coding: utf-8 -*-

# Copyright 2008-2023 Sebastian Hasait
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

# (hasait ...at... web ...dot... de)

import os
import sys
import configparser
import pwd
import grp
import stat
import subprocess
import queue
import threading
import signal
import traceback

recursive = False
verbose = 0
dry = False
encoding = 'utf-8'

cache = threading.local()

###### usage
def usage():
	print(sys.argv[0], """[-R|--recursive] [-n|--dry] [-v|--verbose] [-h|--help] [<path>...]"

Set permissions, ACLs and ownership as configured by files of name "..aclman" - one file configures
all files and directories below (see examples).
It is possible to override configuration by placing additional "..aclman" files in subdirectories.

	-R	recursive - traverse subdirectories
	-n	dry - do not modify anything
	-v	verbose - output more messages (multiple times to increase)
	-h	display help
	<path>	the file or directory to modify, defaults to .
	
	The file "..aclman" contains sections like this:
	[/bin/*]
	OWNER=root
	GROUP=root
	ACL=u::rwX-,g::r-XD,o::r-X-,d:u::rwx,d:g::r-x,d:o::r-x
	FINAL=true
	
	[/opt/*/*]
	ACL=u::rwX-,g::r-XD,o::r-X-,d:u::rwx,d:g::r-x,d:o::r-x
	
	[/Users/*OP/*]
	ACL=u::rwX-,g::---D,o::----,d:u::rwx,d:g::---,d:o::---
	FINAL=true
	
	
	Example file tree:
	/
	+ org/
	     + ..aclman (see above)
	     + bin/
	     |    + foo
	     |    + bar
	     |    + other/
	     |           + abc
	     |           + def
	     |
	     + opt/
	     |    + tool1/
	     |    |      + file1
	     |    |
	     |    + tool2/
	     |    |      + file2
	     |    |
	     |    + file3
	     |
	     + Users/
	            + user1/
	            |      + user1file1
	            |
	            + user2/
	                   + user2file1
	                   + user2file2
	
	Example 1:
	/org/Users/> aclman -R .
	- "." ("Users/") is also visited, but not changed because no section of "..aclman" matches
	- change ownership of "user1/" and "user1file1" to "user1".
	- change owning group of "user1/" and "user1file1" to primary group of "user1".
	- change ownership of "user2/", "user2file1" and "user2file2" to "user2".
	- change owning group of "user2/", "user2file1" and "user2file2" to primary group of "user2".
	
	Example 2:
	/org/> aclman ./opt/file3
	- nothing is changed because "/opt/*/*" matches everything two or more levels down, but "file3"
	  is one level down
	
	Format of ACLs:
	ACL: <ACE>[,<ACE>]*
	ACE: <Subject>:<Permission>|default:<Subject>:<Permission>
	Subject:
		u: (owner) (Permission4)
		g: (owning group) (Permission4)
		o: (other) (Permission4)
		u:<user> (user) (Permission3)
		g:<group> (group) (Permission3)
		m: (mask) (Permission3)
	Permission:
		Position 1: (list for directories, read for files)
			r(set)
			-(clear)
			*(no change)
		Position 2: (create files for directories, write for files)
			w(set)
			-(clear)
			*(no change)
		Position 3: (access files for directories, execute for files)
			x(set)
			-(clear)
			*(no change)
			X(set for dirs, no change for owner for files, copy from owner for files)
			D(set for dirs,clear for files)
		Position 4: (setuid, setgid, sticky - only valid for owner, owning group and other)
			s(set)
			-(clear)
			*(no change)
			S(set for dirs, no change for files)
			Z(clear for dirs, no change for files)
			D(set for dirs,clear for files)
""")

###### log

log_lock = threading.Lock()

def log(level, *args):
	if level <= verbose:
		with log_lock:
			print("[" + cache.name + "] " + " ".join(map(str, args)))

###### execute
def execute(indent, *args):
	log(1, indent, "Execute", *args)
	if not dry:
		childprocess = subprocess.Popen(args)
		if childprocess.wait() != 0:
			raise RuntimeError("Process " + " ".join(map(str, args)) + " failed: " + str(childprocess.returncode))

###### RE

nonexecfileexts = [
	"7z",
	"ani", "avi",
	"bat", "bik", "bin", "bmp", "bup", "bz2",
	"c", "cab", "cfg", "chm", "civ5mod", "class", "cmd", "conf", "cpp", "crt", "csr", "css", "csv", "cue",
	"dat", "db", "deb", "desc", "dll", "dmg", "doc", "docx", "ds_store", "dtd", "dvr-ms",
	"ear", "exe",
	"gif", "gz",
	"h", "hlp", "htm", "html",
	"ico", "ifo", "img", "inf", "ini", "iso",
	"jar", "java", "jpg",
	"kdbx", "key",
	"ldif", "lnk", "log",
	"m3u", "manifest", "md5", "mdf", "mds", "mkv", "mov", "mp3", "mp4", "mpeg", "mpg", "msi",
	"nfo", "nrg",
	"odg", "ods", "odt", "otg", "ots", "ott",
	"pdf", "pdx", "pem", "pit", "png", "ppt", "pptx", "properties",
	"rar", "reg", "rpm", "rtf",
	"sd7", "srt", "sub", "svg", "sxc", "sxw",
	"tar", "tgz", "tif", "torrent", "ttf", "txt",
	"url",
	"vbox-extpack", "vdf", "vob",
	"war", "wav", "wma", "wmv",
	"xls", "xlsx", "xml",
	"zip", "zoo"
]

###### encode
def encodepath(path):
	return "\"" + path.replace("\"", "\\\"").replace("$", "\\$").replace("`", "\\`").replace("!", "\\!").replace("&", "\\&") + "\""

###### getpgrp

def getpgrp(user):
	if user in cache.pgrp:
		return cache.pgrp[user]
	
	pgid = pwd.getpwnam(user).pw_gid
	pgrp = grp.getgrgid(pgid).gr_name
	cache.pgrp[user] = pgrp
	return pgrp

###### getuid

def getuid(name):
	if name in cache.uid:
		return cache.uid[name]
	
	uid = pwd.getpwnam(name)[2]
	cache.uid[name] = uid
	return uid

###### getgid

def getgid(name):
	if name in cache.gid:
		return cache.gid[name]
	
	gid = grp.getgrnam(name)[2]
	cache.gid[name] = gid
	return gid

###### chown
def chown(path, owner, group, st = None, indent = ""):
	if not st:
		st = os.lstat(path)
	
	uid = -1
	if owner:
		try:
			uid = getuid(owner)
			if uid == st.st_uid:
				uid = -1
		except KeyError:
			log(0, indent, "Ignoring unknown owner, using root instead: ", owner)
			uid = 0
	
	gid = -1
	if group:
		try:
			gid = getgid(group)
			if gid == st.st_gid:
				gid = -1
		except KeyError:
			log(0, indent, "Unknown group, using root instead: ", group)
			gid = 0
	
	if uid != -1 or gid != -1:
		log(1, indent, "chown", uid, gid, path)
		if not dry:
			os.lchown(path, uid, gid)

###### parseace
def parseace(acestring, st):
	lr = acestring
	sub = ""
	lh, _, lr = lr.partition(":")
	# [d[efault:]]
	if lh in ["d", "default"]:
		sub += "d:"
		lh, _, lr = lr.partition(":")
	# [u[ser]:]|g[roup]:|o[ther]:|m[ask]:
	if lh in ["u", "user"]:
		sub += "u:"
		lh, _, lr = lr.partition(":")
	elif lh in ["g", "group"]:
		sub += "g:"
		lh, _, lr = lr.partition(":")
	elif lh in ["o", "other"]:
		sub += "o:"
		lh, _, lr = lr.partition(":")
		if len(lh) > 0:
			raise RuntimeError("Other can not have a name: " + lh)
	elif lh in ["m", "mask"]:
		sub += "m:"
		lh, _, lr = lr.partition(":")
		if len(lh) > 0:
			raise RuntimeError("Mask can not have a name: " + lh)
	else:
		sub += "u:"
	# lh is empty or uid/gid
	sub += lh
	# lr contains (r|-|*)(w|-|*)(x|-|*)
	vrs = [ "-", "*", "r"]
	vws = [ "-", "*", "w"]
	vxs = [ "-", "*", "x", "X", "D"]
	vss = [ "-", "*", "s", "S", "Z", "D"]
	sbits = { "u:" : stat.S_ISUID, "g:" : stat.S_ISGID, "o:" : stat.S_ISVTX}
	if lr[0] not in vrs or lr[1] not in vws or lr[2] not in vxs:
		raise RuntimeError("Unknown keyword, expected \"(" + "|".join(vrs) + ")(" + "|".join(vws) + ")(" + "|".join(vxs) + ")\": " + lr)
	r = vrs.index(lr[0]) - 1
	w = vws.index(lr[1]) - 1
	x = vxs.index(lr[2]) - 1
	log(4, "parceace:", "acestring", acestring, "sub", sub, "lh", lh, "lr", lr, "st", st)
	# get s from stat or optional fourth field
	s = 0
	if st:
		if sub in sbits:
			bits = sbits[sub]
			s = 1 if st.st_mode & bits == bits else -1
	elif len(lr) > 3:
		if sub not in sbits:
			raise RuntimeError("Fourth permission only allowed for \"" + "\", \"".join(list(sbits.keys())) + "\" and not for \"" + sub + "\"")
		if lr[3] not in vss:
			raise RuntimeError("Only \"" + "\", \"".join(vss) + "\" are allowed for fourth permission and not \"" + lr[3] + "\"")
		s = vss.index(lr[3]) - 1
	
	log(4, "parceace:", "r", r, "w", w, "x", x, "s", s)
	return [sub, r, w, x, s]

###### getfacl
def getfacl(path, st = None):
	if not st:
		st = os.lstat(path)
	acl = {}
	childprocess = subprocess.Popen(["getfacl", path], stdout = subprocess.PIPE, stderr = subprocess.PIPE)
	childstdout = childprocess.communicate()[0]
	if childprocess.returncode != 0:
		raise RuntimeError("getfacl failed: " + str(childprocess.returncode))
	childstdoutstr = childstdout.decode(encoding)
	for line in childstdoutstr.splitlines():
		if len(line) == 0 or line.startswith("#") or line.isspace():
			continue
		ace = parseace(line, st)
		acl[ace[0]] = ace
	return acl

###### parseacl
def parseacl(aclstring):
	acl = {}
	for acestring in aclstring.split(","):
		ace = parseace(acestring, None)
		acl[ace[0]] = ace
	return acl

###### createchanges
def createchanges(curacl, newacl, bigvalues, replace, indent = ""):
	log(3, indent, "Calculate difference between ACLs")
	log(3, indent, "Cur ACL", curacl)
	log(3, indent, "New ACL", newacl)
	mods = []
	addaces = []
	modaces = []
	rmaces = []
	for sub in newacl.keys():
		newace = newacl[sub]
		if sub in curacl:
			curace = curacl[sub]
			if sub in ["u:", "g:", "o:"]:
				# special handling of owning group because of ext acl
				for i in ([1, 2, 3, 4] if sub in ["u:", "o:"] else [4]):
					na = newace[i]
					ca = curace[i]
					if i >= 3 and na >= 2:
						na = bigvalues[i - 3][na - 2]
					if na != 0 and na != ca:
						op = "-" if na == -1 else "+"
						if i == 4:
							mod = op + "t" if sub == "o:" else sub[0] + op + "s"
						else:
							mod = sub[0] + op + ["r", "w", "x"][i - 1]
						log(2, indent, "Modify mod", mod)
						mods.append(mod)
			if sub not in ["u:", "o:"]:
				changed = False
				mod = ""
				for i in 1, 2, 3:
					na = newace[i]
					ca = curace[i]
					if i >= 3 and na >= 2:
						na = bigvalues[i - 3][na - 2]
					a = ca if na == 0 else na
					mod = mod + ("-" if a == -1 else ["r", "w", "x"][i - 1])
					if na != 0 and na != ca:
						changed = True
				if changed:
					log(2, indent, "Modify ACE", sub, mod)
					modaces.append(sub + ":" + mod)
		else:
			# never true: sub in ["u:", "g:", "o:"]:
			mod = ""
			for i in 1, 2, 3:
				na = newace[i]
				if i >= 3 and na >= 2:
					na = bigvalues[i - 3][na - 2]
				mod = mod + ("-" if na == -1 else ["r", "w", "x"][i - 1])
			log(2, "Add ACE", sub, mod)
			addaces.append(sub + ":" + mod)
	
	if replace:
		for sub in curacl.keys():
			if sub not in newacl:
				log(2, indent, "Remove ACE", sub)
				rmaces.append(sub)
	
	return mods, addaces, modaces, rmaces

###### chacl
def chacl(path, newacl, removeaces = True, st = None, indent = ""):
	if not st:
		st = os.lstat(path)
	isdir = stat.S_ISDIR(st.st_mode)
	curacl = getfacl(path, st)
	mods, addaces, modaces, rmaces = createchanges(curacl, newacl, [[1, 1], [1, -1, 1]] if isdir else [[curacl["u:"][3], -1], [0, 0, -1]], removeaces, indent)
	if len(mods) > 0:
		execute(indent, "chmod", ",".join(mods), path)
	if len(rmaces) > 0:
		execute(indent, "setfacl", "-x", ",".join(rmaces), path)
	if len(modaces) > 0:
		log(1, "curacl: ", curacl)
		execute(indent, "setfacl", "-m", ",".join(modaces), path)
	if len(addaces) > 0:
		execute(indent, "setfacl", "-m", ",".join(addaces), path)

###### readconfig
def readconfig(path, indent = ""):
	if not os.path.isdir(path):
		return readconfig(os.path.dirname(path), indent)
	if path in cache.config:
		log(4, indent, "Config cache hit for", path)
		return cache.config[path]
	log(4, indent, "Create config for", path)
	config = None
	for pathentry in os.listdir(path):
		if pathentry.startswith("..aclman"):
			configfile = os.path.join(path, pathentry)
			log(3, indent, "Found configfile", configfile)
			if not config:
				config = configparser.ConfigParser()
			config.read(configfile)
	updir = os.path.join(path, os.pardir)
	if os.path.exists(updir) and not os.path.samefile(updir, path):
		updir = os.path.abspath(updir)
		parentconfig = readconfig(updir, indent + "  ")
		if parentconfig:
			log(3, indent, "Merge parentconfig")
			if not config:
				config = configparser.ConfigParser()
			basename = os.path.basename(path)
			lenbasename = len(basename)
			globalfinal = -1
			if parentconfig.has_section("/*"):
				section = "/*"
				if parentconfig.has_option(section, "FINAL"):
					finalvalue = parentconfig.get(section, "FINAL").lower()
					if finalvalue in ("true", "yes"):
						globalfinal = 1
					elif finalvalue not in ("false", "no"):
						raise RuntimeError("Invalid value for FINAL '" + finalvalue + "' in " + path)
			if globalfinal == 1:
				for section in config.sections():
					log(0, indent, "Tried to override global final section", section, "in", path)
					config.remove_section(section)
			added = {}
			for section in parentconfig.sections():
				nsection = None
				nprio = -1
				setowner = -1
				setgroup = -1
				final = -1
				if parentconfig.has_option(section, "FINAL"):
					finalvalue = parentconfig.get(section, "FINAL").lower()
					if finalvalue in ("true", "yes"):
						final = 1
					elif finalvalue not in ("false", "no"):
						raise RuntimeError("Invalid value for FINAL '" + finalvalue + "' in " + path)
				if section == "/*":
					nsection = "/*"
				elif section[0:3] == "/*/":
					nsection = section[2:]
					nprio = 0
				elif section[0:4] == "/*O/":
					nsection = section[3:]
					setowner = 1
					nprio = 0
				elif section[0:4] == "/*G/":
					nsection = section[3:]
					setgroup = 1
					nprio = 0
				elif section[0:5] == "/*OG/":
					nsection = section[4:]
					setowner = 1
					setgroup = 1
					nprio = 0
				elif section[0:5] == "/*OP/":
					nsection = section[4:]
					setowner = 1
					setgroup = 2
					nprio = 0
				elif section[0:4] == "/*P/":
					nsection = section[3:]
					setgroup = 2
					nprio = 0
				elif section[0:lenbasename + 2] == "/" + basename + "/":
					nsection = section[lenbasename + 1:]
					nprio = 1
				if nsection:
					if config.has_section(nsection) and final == 1 and not nsection in added:
						log(0, indent, "Tried to override final section", nsection, "from section", section, "in", path)
						config.remove_section(nsection)
						del added[nsection]
					if nsection in added and added[nsection] < nprio:
						log(4, indent, "Replace section", nsection, "with section", section, "in", path, "because of prio")
						config.remove_section(nsection)
						del added[nsection]
					if nsection in added and added[nsection] == nprio:
						log(0, indent, "Section conflict", nsection, "vs", section, "in", path)
					if not config.has_section(nsection):
						log(4, indent, "Copy parentsection", section, "to section", nsection)
						config.add_section(nsection)
						added[nsection] = nprio
						for option, value in parentconfig.items(section):
							log(5, indent, option, "=", value)
							config.set(nsection, option, value)
						if setowner == 1:
							config.set(nsection, "OWNER", basename)
						if setgroup == 1:
							config.set(nsection, "GROUP", basename)
						if setgroup == 2:
							config.set(nsection, "GROUP", getpgrp(basename))
	log(4, indent, "Store permsconfig into cache for", path)
	cache.config[path] = config
	return config

workqueue = queue.Queue()

###### doit
def doit(path, indent = "", st = None):
	if not os.path.lexists(path):
		log(0, indent, "Ignored not existing", path)
		return
	path = os.path.abspath(path)
	if not st:
		st = os.lstat(path)
	if stat.S_ISLNK(st.st_mode):
		log(5, indent, "Ignored link", path)
		return
	isdir = stat.S_ISDIR(st.st_mode)
	if isdir:
		log(2, indent, "DIR", path)
	else:
		log(2, indent, "OTHER", path)
	config = readconfig(path, indent)
	if config == None:
		log(2, indent, "No config")
	if isdir:
		basename = "."
	else:
		basename = os.path.basename(path)
	log(4, indent, "Basename is", basename)
	section = None
	if config:
		if config.has_section("/*"):
			section = "/*"
		if config.has_section("/"):
			section = "/"
		if config.has_section("/" + basename):
			section = "/" + basename
	if section:
		log(3, indent, "Using section", section)
		if verbose >= 4:
			for option, value in config.items(section):
				log(4, indent, option, "=", value)
		
		# IGNORE
		if config.has_option(section, "IGNORE"):
			log(3, indent, "Found IGNORE")
			return
		
		if not isdir and os.path.basename(path).startswith("..aclman"):
			chacl(path, parseacl("u::rw-,g::r--,o::r--"), True, None, indent)
			os.lchown(path, getuid("root"), getgid("root"))
			return
		
		# OWNER, GROUP
		owner = None
		if config.has_option(section, "OWNER"):
			owner = config.get(section, "OWNER")
		group = None
		if config.has_option(section, "GROUP"):
			group = config.get(section, "GROUP")
		chown(path, owner, group, st, indent)
		
		# ACL, DIRACL
		if config.has_option(section, "DIRACL") and isdir:
			aclvalue = config.get(section, "DIRACL")
			replace = True
			if aclvalue.startswith("+"):
				replace = False
				aclvalue = aclvalue[1:]
			newacl = parseacl(aclvalue)
			chacl(path, newacl, replace, st, indent)
		elif config.has_option(section, "ACL"):
			aclvalue = config.get(section, "ACL")
			replace = True
			if aclvalue.startswith("+"):
				replace = False
				aclvalue = aclvalue[1:]
			newacl = parseacl(aclvalue)
			if not isdir:
				for sub in list(newacl.keys()):
					if sub.startswith("d:"):
						del newacl[sub]
				pathlc = path.lower()
				for ext in nonexecfileexts:
					if pathlc.endswith("." + ext):
						log(3, indent, ext + "-file, remove execute permission from ACL")
						for sub in newacl.keys():
							newacl[sub][3] = -1
			chacl(path, newacl, replace, st, indent)
	
	if isdir and recursive:
		for entryname in os.listdir(path):
			entrypath = os.path.join(path, entryname)
			entryst = os.lstat(entrypath)
			if stat.S_ISLNK(entryst.st_mode):
				log(5, indent, "Ignored link", entrypath)
				continue
			entryargs = [entrypath, indent + "\t", entryst]
			entryisdir = stat.S_ISDIR(entryst.st_mode)
			if entryisdir:
				workqueue.put(entryargs)
			else:
				doit(*entryargs)
	log(2, indent, "LEAVE", path)

should_exit = False
should_exit_lock = threading.Lock()

def get_should_exit():
	with should_exit_lock:
		return should_exit

def set_should_exit(value):
	global should_exit
	with should_exit_lock:
		should_exit = value

def worker(name):
	cache.name = name
	cache.pgrp = {}
	cache.uid = {}
	cache.gid = {}
	cache.config = dict([])
	try:
		while True:
			if get_should_exit():
				log(4, "Should exit")
				break
			log(4, "Get next work")
			entry = workqueue.get(True, 1)
			try:
				log(4, "Execute work")
				doit(*entry)
			finally:
				workqueue.task_done()
	except queue.Empty:
		log(4, "Queue empty")
	except:
		ei = sys.exc_info()
		log(0, "Caught exception:", ei[1])
		if verbose >= 4:
			traceback.print_tb(ei[2])
		set_should_exit(True)

def handle_sig_int(signum, frame):
	set_should_exit(True)

###### main

if __name__ == '__main__':
	# parse arguments
	starts = []
	for arg in sys.argv[1:]:
		if arg == "-R":
			recursive = True
		elif arg == "--recursive":
			recursive = True
		elif arg == "-n":
			dry = True
		elif arg == "--dry":
			dry = True
		elif arg == "-v":
			verbose += 1
		elif arg == "--verbose":
			verbose += 1
		elif arg == "-h":
			usage()
			sys.exit(0)
		elif arg == "--help":
			usage()
			sys.exit(0)
		else:
			starts.append(arg)
	
	if len(starts) == 0:
		starts.append(".")
	for start in starts:
		workqueue.put([start])
	
	signal.signal(signal.SIGINT, handle_sig_int)
	
	threads = []
	for i in range(4):
		thread = threading.Thread(target=worker, args = { "Worker " + str(i + 1) })
		thread.start()
		threads.append(thread)
	
	worker("Worker 0")
