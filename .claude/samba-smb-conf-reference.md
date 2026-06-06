# smb.conf Complete Reference — Samba Documentation Index

## File Format

- INI-style: `name = value` pairs grouped in `[sections]`
- Comments: `;` or `#`
- Line continuation: trailing `\`
- Parameter names and section names are **case-insensitive**
- Boolean values accept: `yes/no`, `1/0`, `true/false`

---

## Section Types

| Section | Purpose |
|---------|---------|
| `[global]` | Server-wide settings and defaults for all shares |
| `[homes]` | Dynamic home directory shares — cloned per user on connect |
| `[printers]` | Dynamic printer shares — cloned per printer from printcap |
| `[sharename]` | Named file or print service |

**[homes] behavior:** When a user connects and no explicit share matches their username, Samba clones `[homes]`, sets the share name to the username, and path to their home directory.

**[printers] behavior:** Same mechanism as [homes] but iterates the printcap/CUPS list.

---

## Variable Substitutions

| Variable | Meaning |
|----------|---------|
| `%U` | Session username (as requested by client) |
| `%G` | Primary group of %U |
| `%u` | Username on current service (after mapping) |
| `%g` | Primary group of %u |
| `%h` | Internet hostname of Samba server |
| `%m` | NetBIOS name of client machine |
| `%M` | Internet name of client machine |
| `%L` | NetBIOS name of Samba server |
| `%I` | Client IP address |
| `%i` | Local IP address of connection |
| `%S` | Current service name |
| `%P` | Root directory of current service |
| `%H` | Home directory of %u |
| `%T` | Current date/time |
| `%t` | Date/time compact format (YYYYMMdd_HHMMSS) |
| `%D` | Domain/workgroup of current user |
| `%a` | Client architecture (WinNT, Win95, Win2K, etc.) |
| `%R` | Negotiated protocol (NT1, SMB2_02, SMB3_11, etc.) |
| `%d` | Process ID |
| `%w` | Winbind separator |
| `%$(envvar)` | Environment variable value |

---

## NETWORKING PARAMETERS

| Parameter | Type | Default | Scope | Description |
|-----------|------|---------|-------|-------------|
| `interfaces` | List | auto-detect | Global | Network interfaces Samba listens on |
| `bind interfaces only` | Boolean | no | Global | Restrict SMB/NMBD to specified interfaces only |
| `socket options` | String | (none) | Global | TCP socket options passed to OS |
| `deadtime` | Integer (minutes) | 10080 | Global | Inactivity minutes before connection termination |
| `smb ports` | List | 139, 445 | Global | TCP ports for SMB (139=NetBIOS, 445=direct) |
| `cldap port` | Integer | 389 | Global | CLDAP protocol port |
| `ctdbd socket` | String | (empty) | Global | Unix domain socket for ctdb cluster |

---

## AUTHENTICATION & SECURITY PARAMETERS

| Parameter | Type | Default | Scope | Description |
|-----------|------|---------|-------|-------------|
| `security` | String | user | Global | Auth mode: `user`, `domain`, `ads`, `server`, `share` |
| `workgroup` | String | WORKGROUP | Global | Windows workgroup or domain name |
| `realm` | String | (none) | Global | Kerberos realm for ADS authentication |
| `password server` | String | (none) | Global | DC for password validation in domain/ads mode |
| `guest account` | String | nobody | Global | Unix account used for guest connections |
| `guest ok` | Boolean | no | Service | Allow unauthenticated (guest) access |
| `read only` | Boolean | yes | Service | Share is read-only; alias: `writable = no` |
| `admin users` | List | (empty) | Service | Users with root-level privileges on share |
| `force user` | String | (none) | Service | Force all connections to use this Unix user |
| `force group` | String | (none) | Service | Force all connections to use this Unix group |
| `valid users` | List | (empty) | Service | Users/groups allowed to connect (empty = all) |
| `invalid users` | List | (empty) | Service | Users/groups denied access |
| `write list` | List | (empty) | Service | Users with write access even if read only = yes |
| `read list` | List | (empty) | Service | Users restricted to read-only even if share is writable |
| `allow nt4 crypto` | Boolean | no | Global | Accept weak NT4 crypto (security risk) |
| `client use kerberos` | String | desired | Global | Kerberos usage: `desired`, `required`, `off` |
| `client schannel` | String | yes | Global | Secure netlogon channel: `yes`, `auto`, `no` |
| `client lanman auth` | Boolean | no | Global | DEPRECATED: Allow legacy LANMAN auth |
| `client NTLMv2 auth` | Boolean | yes | Global | Use NTLMv2 authentication |
| `client plaintext auth` | Boolean | no | Global | DEPRECATED: Allow plaintext passwords |
| `client signing` | String | default | Global | SMB signing: `desired`, `required`, `disabled` |
| `client ipc signing` | String | default | Global | Signing for IPC$/DCERPC connections |
| `client ldap sasl wrapping` | String | seal | Global | LDAP traffic encryption: `plain`, `sign`, `seal` |

---

## FILE SYSTEM & PERMISSION PARAMETERS

| Parameter | Type | Default | Scope | Description |
|-----------|------|---------|-------|-------------|
| `path` | String | (required) | Service | Directory path being shared |
| `create mask` | Octal | 0744 | Service | AND mask applied to file permissions on creation |
| `force create mode` | Octal | 0000 | Service | OR mask applied to file permissions on creation |
| `directory mask` | Octal | 0755 | Service | AND mask applied to directory permissions |
| `force directory mode` | Octal | 0000 | Service | OR mask applied to directory permissions |
| `inherit permissions` | Boolean | no | Service | New files/dirs inherit parent directory permissions |
| `inherit owner` | Boolean | no | Service | New files inherit parent directory owner |
| `case sensitive` | String | auto | Service | Case sensitivity: `yes`, `no`, `auto` |
| `default case` | String | lower | Service | Default case for new files: `upper`, `lower` |
| `preserve case` | Boolean | yes | Service | Preserve client-specified case on creation |
| `short preserve case` | Boolean | yes | Service | Preserve case for 8.3-compliant names |
| `wide links` | Boolean | no | Service | Follow symlinks outside share path |
| `allow insecure wide links` | Boolean | no | Global | Bypass unix extensions check for wide links |
| `follow symlinks` | Boolean | yes | Service | Follow symbolic links in share |
| `mangle names` | Boolean | yes | Service | Enable DOS 8.3 name mangling for long filenames |
| `mangling method` | String | hash2 | Service | Algorithm for DOS name generation |
| `delete readonly` | Boolean | no | Service | Allow deletion of read-only files |

---

## ACL & PERMISSION CONTROL PARAMETERS

| Parameter | Type | Default | Scope | Description |
|-----------|------|---------|-------|-------------|
| `nt acl support` | Boolean | yes | Service | Enable NT ACL storage on filesystem |
| `acl map full control` | Boolean | yes | Service | Map POSIX rwx to Windows FULL CONTROL |
| `acl group control` | Boolean | no | Service | Allow group owners to modify ACLs |
| `acl allow execute always` | Boolean | no | Service | Don't check execute perms on file open |
| `acl flag inherited canonicalization` | Boolean | yes | Service | Handle DACL auto-inherit flag correctly |
| `map acl inherit` | Boolean | yes | Service | Map Windows ACL inheritance to Unix |
| `dos filemode` | Boolean | no | Service | Allow Windows filemode attribute changes |
| `store dos attributes` | Boolean | no | Service | Store DOS attributes in filesystem extended attrs |
| `map read only` | Boolean | yes | Service | Map read-only to user permissions |
| `map system` | Boolean | no | Service | Map SYSTEM attribute to execute bits |
| `map hidden` | Boolean | no | Service | Map HIDDEN attribute to dot-files |
| `map archive` | Boolean | yes | Service | Map ARCHIVE attribute |

---

## PROTOCOL & DIALECT PARAMETERS

| Parameter | Type | Default | Scope | Description |
|-----------|------|---------|-------|-------------|
| `server role` | String | auto | Global | `standalone`, `member server`, `domain controller`, `active directory domain controller` |
| `server max protocol` | String | SMB3_11 | Global | Max SMB dialect: `CORE`, `LANMAN1/2`, `NT1`, `SMB2_02/10`, `SMB3_00/02/11` |
| `server min protocol` | String | SMB2_02 | Global | Minimum SMB dialect supported |
| `client max protocol` | String | default | Global | Max client SMB dialect |
| `client min protocol` | String | SMB2_02 | Global | Min client SMB dialect |
| `client ipc max protocol` | String | default | Global | Max protocol for IPC$/DCERPC connections |
| `client ipc min protocol` | String | default | Global | Min protocol for IPC$ connections |
| `enable smb1 only` | Boolean | no | Global | Force SMB1-only mode |
| `nt pipe support` | Boolean | yes | Global | Enable NT named pipes |

---

## ENCRYPTION & SIGNING PARAMETERS

| Parameter | Type | Default | Scope | Description |
|-----------|------|---------|-------|-------------|
| `server signing` | String | default | Global | Server SMB signing: `mandatory`, `auto`, `disabled` |
| `smb encrypt` | String | default | Global | Server-side encryption negotiation |
| `client smb encrypt` | String | default | Global | Client encryption: `off`, `if_required`, `desired`, `required` |
| `client protection` | String | default | Global | Client protection: `default`, `plain`, `sign`, `encrypt` |
| `smb2 max read` | Integer (bytes) | 65536 | Global | Max SMB2+ read request size |
| `smb2 max write` | Integer (bytes) | 65536 | Global | Max SMB2+ write request size |
| `smb3 encryption algorithms` | List | AES-128-GCM, AES-128-CCM, AES-256-GCM, AES-256-CCM | Global | SMB3.11 encryption algorithms |
| `smb3 signing algorithms` | List | AES-128-GMAC, AES-128-CMAC, HMAC-SHA256 | Global | SMB3 signing algorithms |
| `debug encryption` | Boolean | no | Global | Dump SMB3 encryption keys to logs (DANGEROUS) |

---

## LOGGING & DEBUGGING PARAMETERS

| Parameter | Type | Default | Scope | Description |
|-----------|------|---------|-------|-------------|
| `log level` | String | 1 | Global | Verbosity: 0–10, or `module:level` combinations |
| `log file` | String | /var/log/samba/log.%m | Global | Log file path; %m = client, %I = IP |
| `max log size` | Integer (KB) | 5000 | Global | Max log file size before rotation |
| `syslog` | Integer | 0 | Global | Syslog facility (0=disable) |
| `syslog only` | Boolean | no | Global | Send output to syslog only, not file |
| `debug pid` | Boolean | no | Global | Include PID in log messages |
| `debug uid` | Boolean | no | Global | Include UID/GID in log messages |
| `debug timestamp` | Boolean | yes | Global | Include timestamp in log messages |
| `debug hires timestamp` | Boolean | yes | Global | Use microsecond resolution timestamps |
| `auth event notification` | Boolean | no | Global | Stream auth events to message bus |

---

## PERFORMANCE & CACHING PARAMETERS

| Parameter | Type | Default | Scope | Description |
|-----------|------|---------|-------|-------------|
| `aio read size` | Integer (bytes) | 1 | Service | Min size for async reads (0=never, 1=always) |
| `aio write size` | Integer (bytes) | 1 | Service | Min size for async writes |
| `aio write behind` | String | (empty) | Service | Files to write asynchronously (veto-file syntax) |
| `aio max threads` | Integer | 100 | Global | Max async I/O threads per smbd process |
| `write cache size` | Integer (bytes) | 0 | Service | Write cache buffer size (0=disabled) |
| `max connections` | Integer | 0 | Service | Max simultaneous connections (0=unlimited) |
| `oplocks` | Boolean | yes | Service | Enable opportunistic locking |
| `level2 oplocks` | Boolean | yes | Service | Enable Level 2 oplocks |
| `oplock break wait time` | Integer (ms) | 0 | Global | Wait time for oplock break response |
| `veto oplock files` | String | (empty) | Service | Files to disable oplocks on |
| `blocking locks` | Boolean | yes | Service | Queue lock requests until timeout |

---

## SHARE & BROWSING PARAMETERS

| Parameter | Type | Default | Scope | Description |
|-----------|------|---------|-------|-------------|
| `comment` | String | (empty) | Service | Description shown in share browser |
| `browseable` | Boolean | yes | Service | Show share in browse list |
| `browse list` | Boolean | yes | Global | Serve browse list to clients |
| `available` | Boolean | yes | Service | Enable/disable service without removing it |
| `administrative share` | Boolean | no | Service | Mark as admin share (like C$, ADMIN$) |
| `veto files` | String | (empty) | Service | Files to hide and deny access to |
| `hide files` | String | (empty) | Service | Files to hide in directory listings (still accessible) |
| `hide dot files` | Boolean | yes | Service | Hide Unix dot files |
| `hide special files` | Boolean | no | Service | Hide special files (LNK, INF, etc.) |
| `hide unreadable` | Boolean | no | Service | Hide files unreadable by current user |
| `hide unwriteable files` | Boolean | no | Service | Hide files unwriteable by current user |
| `access based share enum` | Boolean | no | Service | Only show shares user can actually access |
| `csc policy` | String | manual | Service | Client-side caching: `manual`, `documents`, `programs`, `disable` |
| `copy` | String | (empty) | Service | Clone parameters from another named service |
| `default service` | String | (none) | Global | Fallback service for nonexistent share requests |

---

## PRINTING PARAMETERS

| Parameter | Type | Default | Scope | Description |
|-----------|------|---------|-------|-------------|
| `printable` | Boolean | no | Service | Enable printing on service |
| `printing` | String | default | Global/Service | Print backend: `cups`, `lpstat`, `lprng`, `aix`, `hpux`, `bsd`, `qnx` |
| `printcap name` | String | /etc/printcap | Global | Printcap file or "lpstat" |
| `load printers` | Boolean | yes | Global | Auto-load printers from printcap |
| `printer name` | String | %S | Service | Printer name sent to backend commands |
| `print command` | String | (varies) | Service | Command to submit print spool file |
| `lpq command` | String | (varies) | Service | Command to list print queue |
| `lprm command` | String | (varies) | Service | Command to remove job from queue |
| `lppause command` | String | (varies) | Service | Command to pause printer |
| `lpresume command` | String | (varies) | Service | Command to resume printer |
| `queuepause command` | String | (varies) | Service | Command to pause queue |
| `queueresume command` | String | (varies) | Service | Command to resume queue |
| `cups server` | String | (empty) | Global | CUPS server hostname:port |
| `cups connection timeout` | Integer (seconds) | 30 | Global | CUPS connection timeout |
| `cups options` | String | (empty) | Service | CUPS-specific print options |
| `cups encrypt` | String | no | Global | CUPS encryption: `auto`, `yes`, `no` |
| `addprinter command` | String | (empty) | Global | Script to add printer via Print Wizard |
| `deleteprinter command` | String | (empty) | Global | Script to delete printer |
| `default devmode` | Boolean | yes | Service | Generate default device mode for printers |

---

## WINS & NAME RESOLUTION PARAMETERS

| Parameter | Type | Default | Scope | Description |
|-----------|------|---------|-------|-------------|
| `wins server` | String | (empty) | Global | WINS server IP address(es) |
| `wins support` | Boolean | no | Global | Enable this server as WINS server |
| `wins hook` | String | (empty) | Global | Script called on WINS database updates |
| `dns proxy` | Boolean | no | Global | Enable DNS-to-NetBIOS proxy |
| `name resolve order` | List | lmhosts, host, wins, bcast | Global | Hostname resolution order |
| `allow dns updates` | String | secure only | Global | DNS updates: `disabled`, `secure only`, `nonsecure` |
| `additional dns hostnames` | String | (empty) | Global | Additional DNS names for this host |

---

## DOMAIN CONTROLLER & AD PARAMETERS

| Parameter | Type | Default | Scope | Description |
|-----------|------|---------|-------|-------------|
| `domain logons` | Boolean | no | Global | Enable domain logon service (NT4-style) |
| `domain master` | Boolean | no | Global | Enable WAN-wide browse list collation |
| `local master` | Boolean | yes | Global | Participate in browse master elections |
| `preferred master` | Boolean | no | Global | Preferred master browser |
| `logon path` | String | \\%N\%U\profile | Global | Path to user profile directory |
| `logon home` | String | \\%N\%U | Global | Home directory path for login |
| `logon drive` | String | Z: | Global | Drive letter for logon home directory |
| `logon script` | String | (empty) | Global | Batch file executed at login |
| `add user script` | String | (empty) | Global | Script to create Unix users on demand |
| `add machine script` | String | (empty) | Global | Script to create machine accounts |
| `add group script` | String | (empty) | Global | Script to create Unix groups |
| `delete user script` | String | (empty) | Global | Script to delete Unix users |
| `delete group script` | String | (empty) | Global | Script to delete Unix groups |
| `add user to group script` | String | (empty) | Global | Script to add user to group |
| `remove user from group script` | String | (empty) | Global | Script to remove user from group |
| `dcerpc endpoint servers` | List | (many) | Global | Enabled RPC endpoint servers |
| `allow dcerpc auth level connect` | Boolean | no | Global | Allow weak DCERPC_AUTH_LEVEL_CONNECT |

---

## IDENTITY MAPPING & WINBIND PARAMETERS

| Parameter | Type | Default | Scope | Description |
|-----------|------|---------|-------|-------------|
| `idmap config DOMAIN : backend` | String | tdb | Global | ID mapping backend: `tdb`, `tdb2`, `ldap`, `rid`, `ad`, `rfc2307`, `nss`, `hash`, `autorid` |
| `idmap config DOMAIN : range` | Range | 1000000-1999999 | Global | UID/GID range for idmap backend |
| `algorithmic rid base` | Integer | 1000 | Global | Base RID for algorithmic UID/GID mapping |
| `winbind cache time` | Integer (seconds) | 300 | Global | Winbind cache expiration time |
| `winbind use default domain` | Boolean | no | Global | Omit DOMAIN\ prefix from %u substitution |
| `idmap negative cache time` | Integer (seconds) | 120 | Global | Cache time for failed identity lookups |

---

## KERBEROS PARAMETERS

| Parameter | Type | Default | Scope | Description |
|-----------|------|---------|-------|-------------|
| `kerberos method` | String | default | Global | Keytab source: `default`, `secrets and keytab`, `dedicated keytab` |
| `dedicated keytab file` | String | (empty) | Global | Path to dedicated keytab file |
| `create krb5 conf` | Boolean | yes | Global | Allow winbind to create krb5.conf |

---

## CLUSTER & HIGH AVAILABILITY PARAMETERS

| Parameter | Type | Default | Scope | Description |
|-----------|------|---------|-------|-------------|
| `clustering` | Boolean | no | Global | Enable ctdb clustering mode |
| `cluster addresses` | String | (empty) | Global | IP addresses to register for cluster |
| `ctdb timeout` | Integer (ms) | 0 | Global | Timeout for ctdb operations |
| `ctdb locktime warn threshold` | Integer (ms) | 0 | Global | Log warning if ctdb locks held too long |
| `allow unsafe cluster upgrade` | Boolean | no | Global | Allow different Samba versions in cluster |

---

## REGISTRY & CONFIGURATION PARAMETERS

| Parameter | Type | Default | Scope | Description |
|-----------|------|---------|-------|-------------|
| `config backend` | String | file | Global | Config storage: `file` or `registry` |
| `include` | String | (empty) | Global | Include another config file |
| `registry shares` | Boolean | no | Global | Load shares from registry in addition to file |
| `lock directory` | String | /var/lib/samba | Global | Directory for lock and TDB files |
| `state directory` | String | /var/lib/samba | Global | Directory for persistent state TDB files |
| `cache directory` | String | /var/cache/samba | Global | Directory for cache TDB files |
| `private dir` | String | /var/lib/samba/private | Global | Directory for sensitive data (secrets.tdb, etc.) |
| `binddns dir` | String | /var/lib/samba/bind-dns | Global | BIND DNS configuration directory |

---

## SCRIPT & COMMAND EXECUTION PARAMETERS

| Parameter | Type | Default | Scope | Description |
|-----------|------|---------|-------|-------------|
| `shutdown script` | String | (empty) | Global | Script executed on system shutdown |
| `abort shutdown script` | String | (empty) | Global | Script to stop shutdown initiated via SMB |
| `panic action` | String | (empty) | Global | Command executed on smbd crash |
| `check password script` | String | (empty) | Global | Script to validate password complexity |
| `add share command` | String | (empty) | Global | Script to dynamically add shares |
| `change share command` | String | (empty) | Global | Script to modify share definitions |
| `delete share command` | String | (empty) | Global | Script to delete shares |

---

## VFS & FILESYSTEM MODULE PARAMETERS

| Parameter | Type | Default | Scope | Description |
|-----------|------|---------|-------|-------------|
| `vfs objects` | List | (none) | Service | VFS modules to load |
| `unix extensions` | Boolean | yes | Service | Enable UNIX extensions for SMB clients |
| `change notify` | Boolean | yes | Global | Reply to file change notify requests |

**Common VFS modules:** `audit`, `default_quota`, `dfs_samba4`, `fake_acls`, `full_audit`, `recycle`, `shadow_copy2`, `streams_xattr`

---

## USERSHARE PARAMETERS

| Parameter | Type | Default | Scope | Description |
|-----------|------|---------|-------|-------------|
| `usershare path` | String | (empty) | Global | Directory for user-defined share definitions |
| `usershare max shares` | Integer | 0 | Global | Max user shares allowed (0=disabled) |
| `usershare owner only` | Boolean | yes | Global | Only user-owned directories can be shared |
| `usershare allow guests` | Boolean | no | Global | Allow guest access in usershares |
| `usershare prefix allow list` | List | (empty) | Global | Restrict shared paths to these prefixes |
| `usershare prefix deny list` | List | (empty) | Global | Forbidden path prefixes for sharing |
| `usershare template share` | String | (empty) | Global | Template share for new usershares |

---

## COMMON MINIMAL CONFIGURATIONS

### Simple File Server (standalone)
```ini
[global]
    workgroup = WORKGROUP
    server string = Samba File Server
    security = user
    log file = /var/log/samba/log.%m
    log level = 1

[data]
    path = /srv/samba/data
    read only = no
    browseable = yes
    valid users = @smbusers
    create mask = 0664
    directory mask = 0775
    force group = smbusers
```

### Active Directory Member Server
```ini
[global]
    workgroup = MYDOMAIN
    realm = MYDOMAIN.EXAMPLE.COM
    security = ads
    server role = member server
    idmap config * : backend = tdb
    idmap config * : range = 10000-19999
    idmap config MYDOMAIN : backend = rid
    idmap config MYDOMAIN : range = 20000-999999
    winbind use default domain = yes
    log file = /var/log/samba/log.%m
    log level = 1
```

### Active Directory Domain Controller
```ini
[global]
    workgroup = MYDOMAIN
    realm = MYDOMAIN.EXAMPLE.COM
    server role = active directory domain controller
    dns forwarder = 8.8.8.8

[sysvol]
    path = /var/lib/samba/sysvol
    read only = no

[netlogon]
    path = /var/lib/samba/sysvol/mydomain.example.com/scripts
    read only = yes
```
