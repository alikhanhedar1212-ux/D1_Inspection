"""Always reap SSH control transports, including failed graceful shutdown."""
import json,subprocess,time

def close_transport(proc):
    if proc is None:return
    try:
        if proc.stdin is not None:
            proc.stdin.write(json.dumps({'sent':time.monotonic(),'x':0.,'y':0.,'w':0.,'reason':'导航关闭','shutdown':True})+'\n')
            proc.stdin.flush();proc.stdin.close()
    except (BrokenPipeError,OSError,ValueError):pass
    try:proc.wait(timeout=1)
    except subprocess.TimeoutExpired:
        proc.terminate()
        try:proc.wait(timeout=1)
        except subprocess.TimeoutExpired:proc.kill();proc.wait(timeout=1)
    finally:
        for stream in (proc.stdin,proc.stdout):
            if stream is not None:
                try:stream.close()
                except (OSError,ValueError):pass
