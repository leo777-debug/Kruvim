"""Apply an aggregate Windows job commit limit to an isolated Playwright browser tree.

Does not change host RAM/boot settings or touch existing user browser processes.
This cannot qualify physical 4/8 GB hardware. Needs Node, installed Edge/Chrome,
the generated fixtures, and the local Vite verification server.
"""
import ctypes as c
from ctypes import wintypes as w
import json
from pathlib import Path
import shutil
import subprocess
import sys
import time

class Basic(c.Structure):
    _fields_=[('process_time',c.c_longlong),('job_time',c.c_longlong),('flags',w.DWORD),('min_ws',c.c_size_t),('max_ws',c.c_size_t),('active_limit',w.DWORD),('affinity',c.c_size_t),('priority',w.DWORD),('scheduling',w.DWORD)]
class IO(c.Structure):
    _fields_=[(name,c.c_ulonglong) for name in ['read_ops','write_ops','other_ops','read_bytes','write_bytes','other_bytes']]
class Extended(c.Structure):
    _fields_=[('basic',Basic),('io',IO),('process_limit',c.c_size_t),('job_limit',c.c_size_t),('peak_process',c.c_size_t),('peak_job',c.c_size_t)]

def main():
    channel=sys.argv[1] if len(sys.argv)>1 else 'msedge'
    gib=float(sys.argv[2]) if len(sys.argv)>2 else 2
    if channel not in ['chrome','msedge'] or not 0.5<=gib<=8: raise ValueError('Use chrome/msedge and 0.5–8 GiB')
    profile=sys.argv[3] if len(sys.argv)>3 else 'standard'
    if profile not in ['standard','conservative']:raise ValueError('Unknown policy profile')
    root=Path(__file__).resolve().parents[1]
    evidence=root.parent.parent/'kruvim-paid-local-followup-20261117'
    evidence.mkdir(exist_ok=True)
    stem=f'{channel}-{gib:g}gib-{profile}'
    gate=evidence/(stem+'.start');gate.unlink(missing_ok=True)
    report=evidence/(stem+'-browser.json')
    kernel=c.WinDLL('kernel32',use_last_error=True)
    kernel.CreateJobObjectW.argtypes=[c.c_void_p,w.LPCWSTR];kernel.CreateJobObjectW.restype=w.HANDLE
    kernel.SetInformationJobObject.argtypes=[w.HANDLE,c.c_int,c.c_void_p,w.DWORD];kernel.SetInformationJobObject.restype=w.BOOL
    kernel.QueryInformationJobObject.argtypes=[w.HANDLE,c.c_int,c.c_void_p,w.DWORD,c.c_void_p];kernel.QueryInformationJobObject.restype=w.BOOL
    kernel.AssignProcessToJobObject.argtypes=[w.HANDLE,w.HANDLE];kernel.AssignProcessToJobObject.restype=w.BOOL
    kernel.CloseHandle.argtypes=[w.HANDLE]
    job=kernel.CreateJobObjectW(None,None)
    if not job: raise c.WinError(c.get_last_error())
    limits=Extended();limits.basic.flags=0x200|0x2000;limits.job_limit=int(gib*1024**3)
    process=None;peak_processes=0
    try:
        if not kernel.SetInformationJobObject(job,9,c.byref(limits),c.sizeof(limits)):raise c.WinError(c.get_last_error())
        process=subprocess.Popen([shutil.which('node'),str(root/'tools/verify-memory-limited.mjs'),channel,str(gate),str(report),profile],cwd=root)
        if not kernel.AssignProcessToJobObject(job,w.HANDLE(int(process._handle))):raise c.WinError(c.get_last_error())
        gate.write_text('assigned')
        deadline=time.monotonic()+600
        while process.poll() is None:
            processes=c.create_string_buffer(32768)
            if kernel.QueryInformationJobObject(job,3,processes,len(processes),None):
                count=c.cast(processes,c.POINTER(w.DWORD))[1];peak_processes=max(peak_processes,int(count))
            if time.monotonic()>deadline:raise TimeoutError('Memory test exceeded 10 minutes')
            time.sleep(.25)
        measured=Extended()
        if not kernel.QueryInformationJobObject(job,9,c.byref(measured),c.sizeof(measured),None):raise c.WinError(c.get_last_error())
        result={'channel':channel,'aggregateCommitLimitBytes':limits.job_limit,'peakCommittedBytes':measured.peak_job,
                'peakSingleProcessBytes':measured.peak_process,'maxJobProcessCount':peak_processes,'exitCode':process.returncode,
                'policyProfile':profile,'scope':'Windows process-tree job limit, not physical low-RAM hardware','browserEvidence':report.name}
        (evidence/(stem+'-job.json')).write_text(json.dumps(result,indent=2))
        print(json.dumps(result),flush=True)
        if process.returncode:raise SystemExit(process.returncode)
    finally:
        # KILL_ON_JOB_CLOSE applies only to this newly launched test process tree.
        kernel.CloseHandle(job);gate.unlink(missing_ok=True)
if __name__=='__main__':main()
