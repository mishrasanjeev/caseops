"""macOS invocation-owned process cleanup; no environment values are retained."""
from __future__ import annotations
import ctypes
from datetime import datetime, UTC
import errno
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

class OwnershipError(RuntimeError):
    pass

def need(ok, code):
    if not ok:
        raise OwnershipError(code)

def utc_created(seconds, microseconds):
    need(type(seconds) is int and type(microseconds) is int and seconds > 0 and 0 <= microseconds < 1000000, 'PROCESS_CREATION_INVALID')
    value = datetime.fromtimestamp(seconds, UTC).replace(microsecond=microseconds)
    text = value.isoformat(timespec='microseconds').replace('+00:00', 'Z')
    parsed = datetime.fromisoformat(text.replace('Z', '+00:00'))
    need(int(parsed.timestamp()) == seconds and parsed.microsecond == microseconds and parsed.isoformat(timespec='microseconds').replace('+00:00', 'Z') == text, 'PROCESS_CREATION_ROUNDTRIP')
    return text

def parse_args(raw):
    need(4 <= len(raw) <= 1048576, 'PROCESS_ARGV_BOUND')
    count = int.from_bytes(raw[:4], sys.byteorder, signed=True)
    need(1 <= count <= 256, 'PROCESS_ARGC_BOUND')
    start = raw.find(b'\0', 4)
    need(start >= 4, 'PROCESS_EXEC_PATH_REQUIRED')
    start += 1
    while start < len(raw) and raw[start] == 0:
        start += 1
    args = []
    for _ in range(count):
        end = raw.find(b'\0', start)
        need(end >= start, 'PROCESS_ARGV_INCOMPLETE')
        args.append(raw[start:end].decode('utf-8', 'strict'))
        start = end + 1
    # kern.procargs2 also returns environment bytes. Do not parse or retain them.
    return args

class _BsdInfo(ctypes.Structure):
    _fields_ = [(name, ctypes.c_uint32) for name in ('flags','status','xstatus','pid','ppid','uid','gid','ruid','rgid','svuid','svgid','rfu')]+[('comm',ctypes.c_char*16),('name',ctypes.c_char*32)]+[(name,ctypes.c_uint32) for name in ('nfiles','pgid','pjobc','tdev','tpgid')]+[('nice',ctypes.c_int32),('start_sec',ctypes.c_uint64),('start_usec',ctypes.c_uint64)]

class MacBackend:
    def __init__(self):
        need(sys.platform == 'darwin', 'MACOS_PROCESS_OWNER_REQUIRED')
        self.lib = ctypes.CDLL('/usr/lib/libproc.dylib', use_errno=True)
        self.lib.proc_pidinfo.argtypes = [ctypes.c_int,ctypes.c_int,ctypes.c_uint64,ctypes.c_void_p,ctypes.c_int]
        self.lib.proc_pidinfo.restype = ctypes.c_int
        self.lib.proc_pidpath.argtypes = [ctypes.c_int,ctypes.c_void_p,ctypes.c_uint32]
        self.lib.proc_pidpath.restype = ctypes.c_int
        self.libc = ctypes.CDLL(None, use_errno=True)
        self.libc.sysctl.argtypes = [ctypes.POINTER(ctypes.c_int),ctypes.c_uint,ctypes.c_void_p,ctypes.POINTER(ctypes.c_size_t),ctypes.c_void_p,ctypes.c_size_t]
        self.libc.sysctl.restype = ctypes.c_int
    def _bsd(self, pid):
        result = _BsdInfo()
        got = self.lib.proc_pidinfo(pid, 3, 0, ctypes.byref(result), ctypes.sizeof(result))
        if got == 0 and ctypes.get_errno() in (errno.ESRCH, errno.ENOENT):
            return None
        need(got == ctypes.sizeof(result) and result.pid == pid, 'PROCESS_IDENTITY_UNAVAILABLE')
        return result
    def _command(self, args, deadline):
        remaining = deadline-time.monotonic()
        need(remaining > 0, 'PROCESS_CLEANUP_DEADLINE')
        result = subprocess.run(args, capture_output=True, timeout=min(2, remaining), env={'PATH':'/usr/bin:/bin:/usr/sbin','LC_ALL':'C','TZ':'UTC'})
        need(len(result.stdout)+len(result.stderr) <= 1048576, 'PROCESS_METADATA_BOUND')
        return result
    def snapshot(self, deadline):
        result = self._command(['/bin/ps','-axo','pid=,ppid=,pgid='], deadline)
        need(result.returncode == 0, 'PROCESS_INVENTORY_REFUSED')
        rows = {}
        for line in result.stdout.decode('ascii','strict').splitlines():
            values = line.split()
            need(len(values) == 3 and all(x.isdecimal() for x in values), 'PROCESS_INVENTORY_GRAMMAR')
            pid, ppid, pgid = map(int, values)
            need(pid > 0 and pid not in rows, 'PROCESS_INVENTORY_DUPLICATE')
            rows[pid] = {'pid':pid,'ppid':ppid,'pgid':pgid}
        return rows
    def _identity(self, pid, deadline):
        before = self._bsd(pid)
        if before is None:
            return None
        executable = ctypes.create_string_buffer(4096)
        need(self.lib.proc_pidpath(pid, executable, len(executable)) > 0, 'PROCESS_EXECUTABLE_UNAVAILABLE')
        executable_path = executable.value.decode('utf-8','strict')
        mib = (ctypes.c_int*3)(1,49,pid);size=ctypes.c_size_t()
        need(self.libc.sysctl(mib,3,None,ctypes.byref(size),None,0) == 0 and 0 < size.value <= 1048576, 'PROCESS_ARGS_UNAVAILABLE')
        buffer=ctypes.create_string_buffer(size.value)
        try:
            need(self.libc.sysctl(mib,3,buffer,ctypes.byref(size),None,0) == 0, 'PROCESS_ARGS_UNAVAILABLE')
            args=parse_args(buffer.raw[:size.value])
        finally:
            ctypes.memset(buffer,0,len(buffer))
        result=self._command(['/usr/sbin/lsof','-nP','-a','-p',str(pid),'-d','cwd','-Fn'],deadline)
        lines=result.stdout.decode('utf-8','strict').splitlines()
        need(result.returncode == 0 and len(lines)==3 and lines[:2]==['p'+str(pid),'fcwd'] and lines[2].startswith('n/'), 'PROCESS_CWD_UNAVAILABLE')
        cwd=str(Path(lines[2][1:]).resolve(strict=True))
        after=self._bsd(pid)
        need(after is not None and all(getattr(before,k)==getattr(after,k) for k in ('pid','pgid','uid','start_sec','start_usec')), 'PROCESS_CHANGED_DURING_ADMISSION')
        return {'pid':pid,'ppid':after.ppid,'pgid':before.pgid,'uid':before.uid,'createdUtc':utc_created(before.start_sec,before.start_usec),'cwd':cwd,'executable':str(Path(executable_path).resolve(strict=True)),'argv':args}
    def identity(self, pid, deadline):
        try:
            return self._identity(pid, deadline)
        except (OwnershipError, OSError, UnicodeError):
            if self._bsd(pid) is None:
                return None
            raise
    def signal_group(self, group, sig):
        os.killpg(group, sig)

_STABLE=('pid','pgid','uid','createdUtc','cwd','executable','argv')
def same_process(before, after):
    return all(before[k] == after[k] for k in _STABLE)

def public_identity(value):
    return {k:v for k,v in value.items() if k!='argv'} | {'argvSha256':hashlib.sha256(json.dumps(value['argv'],ensure_ascii=False,separators=(',',':')).encode()).hexdigest()}

def numeric_snapshot(rows):
    """Retain only exact PID/PPID/PGID triples, never command or environment."""
    if rows is None:
        return None
    result=[]
    for pid,row in sorted(rows.items()):
        values=[row.get(key) for key in ('pid','ppid','pgid')]
        if type(pid) is not int or any(type(value) is not int for value in values) or values[0]!=pid:
            return None
        result.append(values)
    return result

class OwnedGroup:
    """Call sample while waiting; finish owns at most30s within caller deadline."""
    def __init__(self, process, argv, cwd, *, deadline, backend=None):
        self.process=process;self.backend=backend or MacBackend();self.records={};self.original_parent=os.getpid();self.signals=[]
        root=self.backend.identity(process.pid,deadline)
        need(root is not None and root['ppid']==os.getpid() and root['pgid']==process.pid and root['uid']==os.getuid(), 'OWNED_CHILD_ADMISSION_REFUSED')
        need(root['cwd']==str(Path(cwd).resolve(strict=True)) and root['executable']==str(Path(argv[0]).resolve(strict=True)) and root['argv']==list(argv), 'OWNED_CHILD_COMMAND_REFUSED')
        self.records[root['pid']]=root
    def sample(self, deadline):
        observation={'iteration':None,'inputRows':None,'freshRows':None,
                     'currentPids':[],'recordedPids':sorted(self.records),
                     'knownMissingPids':[],'unknownMissingPids':[],'changedPids':[]}
        try:
            rows=self.backend.snapshot(deadline)
            for attempt in range(32):
                observation={'iteration':attempt,'inputRows':numeric_snapshot(rows),'freshRows':None,
                             'currentPids':[],'recordedPids':sorted(self.records),
                             'knownMissingPids':[],'unknownMissingPids':[],'changedPids':[]}
                current=self._admit_snapshot(rows,deadline)
                self.process.poll()
                fresh=self.backend.snapshot(deadline)
                current={pid:value for pid,value in current.items() if pid in fresh}
                changed={pid for pid,value in current.items() if any(fresh[pid][key]!=value[key] for key in ('ppid','pgid'))}
                groups={x['pgid'] for x in self.records.values()}
                known_missing={pid for pid in self.records if pid in fresh and pid not in current}
                unknown_missing={pid for pid,row in fresh.items() if row['pgid'] in groups
                                 and pid not in current and pid not in self.records}
                missing=known_missing | unknown_missing
                observation.update(freshRows=numeric_snapshot(fresh),currentPids=sorted(current),
                                   recordedPids=sorted(self.records),knownMissingPids=sorted(known_missing),
                                   unknownMissingPids=sorted(unknown_missing),changedPids=sorted(changed))
                if not missing and not changed:
                    return current
                # Only an already recorded PID may wait for the next bounded
                # identity observation. If alive it must pass the unchanged
                # exact identity/ancestry checks; if ended it must disappear
                # from a fresh inventory. No signal is authorized meanwhile.
                # New group members still require their COMPLETE current
                # ancestry now, even alongside a known missing PID.
                for pid in unknown_missing:
                    parent=pid;seen=set()
                    while parent not in current:
                        need(parent in fresh and parent not in seen,'PROCESS_GROUP_HAS_UNADMITTED_MEMBER')
                        seen.add(parent);parent=fresh[parent]['ppid']
                need(time.monotonic()<deadline,'PROCESS_CLEANUP_DEADLINE')
                rows=fresh
            raise OwnershipError('PROCESS_INVENTORY_CONVERGENCE_BOUND')
        except Exception as exc:
            if getattr(self,'failure_observation',None) is None:
                value=str(exc)
                code=value if (isinstance(exc,OwnershipError) and 0<len(value)<=128
                               and all(c in 'ABCDEFGHIJKLMNOPQRSTUVWXYZ_0123456789' for c in value)) else type(exc).__name__
                self.failure_observation={'errorClass':type(exc).__name__,'errorCode':code,
                                          'outerConvergenceInventoryLimit':33,'convergenceRoundsLimit':32,
                                          'additionalAncestrySnapshotsUseExistingDeadline':True,
                                          'ownedProcessLimit':1024,
                                          'numericObservation':observation}
            raise
    def _admit_snapshot(self,rows,deadline):
        current={}
        for pid, old in list(self.records.items()):
            if pid not in rows:
                continue
            now=self.backend.identity(pid,deadline)
            if now is None:
                continue
            need(same_process(old,now),'OWNED_PROCESS_IDENTITY_CHANGED')
            if now['ppid'] != old['ppid']:
                self.process.poll()
                fresh=self.backend.snapshot(deadline)
                need(now['ppid']==1 and old['ppid'] not in fresh, 'OWNED_PROCESS_ANCESTRY_CHANGED')
            current[pid]=now
        for _ in range(32):
            added=False
            for pid,row in rows.items():
                if pid in self.records or row['ppid'] not in current:
                    continue
                now=self.backend.identity(pid,deadline)
                if now is None:
                    continue
                need(now['ppid']==row['ppid'] and now['uid']==os.getuid(),'OWNED_DESCENDANT_ADMISSION_REFUSED')
                self.records[pid]=now;current[pid]=now;added=True
            if not added:
                break
        else:
            raise OwnershipError('PROCESS_ANCESTRY_BOUND')
        need(len(self.records)<=1024,'OWNED_PROCESS_COUNT_BOUND')
        return current
    def wait(self, deadline):
        while self.process.poll() is None:
            if time.monotonic()>=deadline:
                return {'exitCode':None,'timedOut':True}
            try:
                self.sample(deadline)
            except (subprocess.TimeoutExpired, OwnershipError):
                if time.monotonic() >= deadline:
                    return {'exitCode':self.process.poll(),'timedOut':True}
                raise
            time.sleep(min(.1,max(0,deadline-time.monotonic())))
        return {'exitCode':self.process.wait(),'timedOut':False}
    def finish(self, deadline):
        end=min(deadline,time.monotonic()+30);error=None
        try:
            current=self.sample(end)
            for sig in (signal.SIGTERM,signal.SIGKILL):
                if not current:
                    break
                # Recheck the complete current group immediately before each signal.
                for group in sorted({x['pgid'] for x in current.values()}):
                    current=self.sample(end)
                    if not any(x['pgid']==group for x in current.values()):
                        continue
                    self.backend.signal_group(group,sig);self.signals.append({'pgid':group,'signal':sig.name})
                grace=min(end,time.monotonic()+(2 if sig==signal.SIGTERM else 3))
                while time.monotonic()<grace:
                    self.process.poll()
                    current=self.sample(end)
                    if not current:
                        break
                    time.sleep(min(.05,max(0,grace-time.monotonic())))
            need(not self.sample(end),'OWNED_PROCESSES_REMAIN')
            need(self.process.poll() is not None,'OWNED_ROOT_NOT_REAPED')
            self.process.wait(timeout=max(.001,end-time.monotonic()))
        except Exception as exc:
            error=type(exc).__name__+(':'+str(exc) if isinstance(exc,OwnershipError) else '')
        return {'complete':error is None,'cleanupError':error,'rootPid':self.process.pid,'rootReaped':self.process.poll() is not None,'ownedIdentities':[public_identity(x) for x in self.records.values()],'signals':self.signals,'cleanupSecondsLimit':30,'callerAbsoluteDeadlineRetained':True,'failureObservation':getattr(self,'failure_observation',None)}
