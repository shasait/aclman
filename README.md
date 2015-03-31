# aclman

Command line based manager for enforcing linux file ownership and ACLs.

What ACLs and ownership to apply is configured by files of name "..aclman" placed somewhere in the directory tree.

### Usage

        aclman [-R|--recursive] [-n|--dry] [-v|--verbose] [-h|--help] [<path>...]

### Options

        -R      recursive - traverse subdirectories
        -n      dry - do not modify anything
        -v      verbose - output more messages (multiple times to increase)
        -h      display help
        <path>  the file or directory to modify, defaults to .

### Configuration
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

Each section name is a path pattern. For each object visited the most specific section is applied.
For wildargs "*" the flags "O" (owner) "P" (primary group) and "G" (group) can be appended to define owner and group depending on the matched path part - this is useful for home directories.
        
Example file tree (used by examples below):

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
          is only one level down

### Format of ACLs

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
                        D(set for dirs, clear for files)
                Position 4: (setuid, setgid, sticky - only valid for owner, owning group and other)
                        s(set)
                        -(clear)
                        *(no change)
                        S(set for dirs, no change for files)
                        Z(clear for dirs, no change for files)
                        D(set for dirs, clear for files)
