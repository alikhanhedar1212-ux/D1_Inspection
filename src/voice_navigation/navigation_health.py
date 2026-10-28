"""Check actual Nav2 lifecycle state before acknowledging a motion task."""
import time

NAMES={'planner_server':'规划器','controller_server':'控制器','bt_navigator':'导航行为树'}

def check_navigation_health(clients,request_factory,timeout=2.,clock=time.monotonic,sleep=time.sleep):
    missing=[NAMES.get(name,name) for name,client in clients.items() if not client.service_is_ready()]
    if missing:raise RuntimeError('导航服务未就绪：'+'、'.join(missing))
    futures={name:client.call_async(request_factory()) for name,client in clients.items()}
    deadline=clock()+timeout
    while any(not f.done() for f in futures.values()):
        if clock()>=deadline:raise RuntimeError('导航节点状态检查超时')
        sleep(.01)
    inactive=[]
    for name,future in futures.items():
        result=future.result()
        if result is None or result.current_state.id!=3:inactive.append(NAMES.get(name,name))
    if inactive:raise RuntimeError('导航节点未激活：'+'、'.join(inactive))
