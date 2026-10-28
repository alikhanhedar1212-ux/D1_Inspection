import unittest
from types import SimpleNamespace as NS
from navigation_health import check_navigation_health

def client(state):
    return NS(service_is_ready=lambda:True,call_async=lambda _:NS(done=lambda:True,result=lambda:NS(current_state=NS(id=state))))

class NavigationHealthTests(unittest.TestCase):
    def test_inactive_controller_and_planner_rejected_despite_active_navigator(self):
        with self.assertRaisesRegex(RuntimeError,'规划器、控制器'):
            check_navigation_health({'planner_server':client(2),'controller_server':client(2),'bt_navigator':client(3)},object)
    def test_active_stack_allowed(self):
        check_navigation_health({'planner_server':client(3),'controller_server':client(3),'bt_navigator':client(3)},object)
    def test_missing_service_rejected(self):
        c=client(3);c.service_is_ready=lambda:False
        with self.assertRaisesRegex(RuntimeError,'未就绪'):check_navigation_health({'controller_server':c},object)
    def test_unresponsive_state_rejected(self):
        c=client(3);c.call_async=lambda _:NS(done=lambda:False)
        with self.assertRaisesRegex(RuntimeError,'超时'):check_navigation_health({'controller_server':c},object,timeout=0)

if __name__=='__main__':unittest.main()
