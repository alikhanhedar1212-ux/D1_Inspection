#include <cassert>
#include <chrono>
#include <thread>
#include <stdexcept>
#include "terminal_replan.cpp"

class TestFollow : public BT::StatefulActionNode {
public:
  TestFollow(const std::string & name, const BT::NodeConfiguration & config)
  : BT::StatefulActionNode(name, config) {}
  static BT::PortsList providedPorts() {return {};}
  BT::NodeStatus onStart() override {return BT::NodeStatus::RUNNING;}
  BT::NodeStatus onRunning() override {return BT::NodeStatus::RUNNING;}
  void onHalted() override {}
};

int main(int argc, char ** argv) {
  rclcpp::init(argc, argv);
  auto tf = std::make_shared<tf2_ros::Buffer>(std::make_shared<rclcpp::Clock>());
  auto bb = BT::Blackboard::create();
  bb->set("tf_buffer", tf);
  geometry_msgs::msg::PoseStamped goal;
  goal.header.frame_id = "map";
  goal.pose.position.x = 1;
  goal.pose.orientation.w = 1;
  bb->set("goal", goal);
  auto position = [&](double x) {
    geometry_msgs::msg::TransformStamped t;
    t.header.frame_id = "map"; t.child_frame_id = "nav_body";
    t.transform.translation.x = x; t.transform.rotation.w = 1;
    tf->setTransform(t, "test", true);
  };
  int calls = 0;
  BT::NodeStatus result = BT::NodeStatus::SUCCESS;
  BT::BehaviorTreeFactory factory;
  factory.registerFromPlugin(argv[1]);
  factory.registerSimpleAction("Plan", [&](BT::TreeNode &) {++calls; return result;});
  auto tree = factory.createTreeFromText(
    "<root main_tree_to_execute='T'><BehaviorTree ID='T'><TerminalReplan goal='{goal}'><Plan/></TerminalReplan></BehaviorTree></root>", bb);
  position(0);
  tree.tickRoot(); tree.tickRoot(); assert(calls == 2); // replan en route
  position(0.85); tree.tickRoot(); assert(calls == 2); // latch inside radius
  position(0.7); tree.tickRoot(); assert(calls == 2); // rotation drift cannot reset
  goal.pose.orientation.z = 1; goal.pose.orientation.w = 0;
  bb->set("goal", goal); tree.tickRoot(); assert(calls == 3); // heading-only new goal
  tree.haltTree(); tree.tickRoot(); assert(calls == 4); // canceled goal resets
  tree.haltTree(); position(1);
  result = BT::NodeStatus::FAILURE;
  assert(tree.tickRoot() == BT::NodeStatus::FAILURE && calls == 5);
  result = BT::NodeStatus::SUCCESS;
  tree.tickRoot(); assert(calls == 6); // failure never counts as a valid path
  tree.tickRoot(); assert(calls == 6); // orientation-only start still planned once
  // Regression: a Decorator resets a SUCCESS child to IDLE. Placing
  // TerminalReplan outside RateController resets its timer after every plan.
  factory.registerFromPlugin(argv[2]);
  factory.registerFromPlugin(argv[3]);
  factory.registerNodeType<TestFollow>("Follow");
  position(0);
  auto measure = [&](const std::string & planning, double seconds) {
    calls = 0;
    auto t = factory.createTreeFromText(
      "<root main_tree_to_execute='T'><BehaviorTree ID='T'><PipelineSequence>" +
      planning + "<Follow/></PipelineSequence></BehaviorTree></root>", bb);
    const auto end = std::chrono::steady_clock::now() + std::chrono::duration<double>(seconds);
    while (std::chrono::steady_clock::now() < end) {
      t.tickRoot();
      std::this_thread::sleep_for(std::chrono::milliseconds(10));
    }
    t.haltTree();
    return calls;
  };
  const auto bad = measure("<TerminalReplan goal='{goal}'><RateController hz='1'><Plan/></RateController></TerminalReplan>", .35);
  const auto good = measure("<RateController hz='1'><TerminalReplan goal='{goal}'><Plan/></TerminalReplan></RateController>", 1.25);
  if (bad < 8 || good != 2) {
    throw std::runtime_error("Replanning rate regression: old=" + std::to_string(bad) + " fixed=" + std::to_string(good));
  }
  position(.75);  // 0.25m from the goal: inside the current 0.30m arrival tolerance.
  const auto old_radius = measure("<RateController hz='1'><TerminalReplan goal='{goal}' radius='0.2'><Plan/></TerminalReplan></RateController>", 1.25);
  const auto matched_radius = measure("<RateController hz='1'><TerminalReplan goal='{goal}' radius='0.3'><Plan/></TerminalReplan></RateController>", 1.25);
  assert(old_radius == 2 && matched_radius == 1);
  position(.65);
  const auto still_approaching = measure("<RateController hz='1'><TerminalReplan goal='{goal}' radius='0.3'><Plan/></TerminalReplan></RateController>", 1.25);
  assert(still_approaching == 2);
  calls = 0;
  auto drift_tree = factory.createTreeFromText(
    "<root main_tree_to_execute='T'><BehaviorTree ID='T'><TerminalReplan goal='{goal}' radius='0.3'><Plan/></TerminalReplan></BehaviorTree></root>", bb);
  position(.75); drift_tree.tickRoot(); drift_tree.tickRoot(); assert(calls == 1);
  position(.65); drift_tree.tickRoot(); assert(calls == 1); // 0.35m: tolerate jitter
  position(.50); drift_tree.tickRoot(); assert(calls == 2); // 0.50m: recover position
  position(.75); drift_tree.tickRoot(); assert(calls == 2); // latch again after recovery
  std::cout << "PASS: bounded terminal latch releases on substantial position drift\n";
  std::cout << "PASS: reproduced 0.20m/0.30m mismatch; terminal replan stops at 0.25m after fix\n";
  std::cout << "PASS: reproduced timer reset (" << bad << " plans/0.35s), corrected nesting (" << good << " plans/1.25s)\n";
  rclcpp::shutdown();
  std::cout << "PASS: dynamic plugin load, en-route replanning, terminal latch, drift, new heading, cancel reset, failure propagation\n";
}
