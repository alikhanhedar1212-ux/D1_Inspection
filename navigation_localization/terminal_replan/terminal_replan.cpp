#include <cmath>
#include "nav2_behavior_tree/bt_conversions.hpp"
#include "behaviortree_cpp_v3/bt_factory.h"
#include "tf2_ros/buffer.h"

// Keep the last valid path during terminal rotation. FollowPath still checks
// every candidate against the live local costmap; this never publishes velocity.
class TerminalReplan : public BT::DecoratorNode
{
public:
  TerminalReplan(const std::string & name, const BT::NodeConfiguration & config)
  : BT::DecoratorNode(name, config), tf_(config.blackboard->get<std::shared_ptr<tf2_ros::Buffer>>("tf_buffer")) {}
  static BT::PortsList providedPorts() {
    return {BT::InputPort<geometry_msgs::msg::PoseStamped>("goal"),
      BT::InputPort<double>("radius", 0.2, "Terminal position tolerance"),
      BT::InputPort<std::string>("robot_base_frame", std::string("nav_body"), "Robot body frame")};
  }
  void halt() override {
    initialized_ = planned_ = latched_ = false;
    BT::DecoratorNode::halt();
  }
private:
  BT::NodeStatus tick() override {
    geometry_msgs::msg::PoseStamped goal;
    if (!getInput("goal", goal)) return BT::NodeStatus::FAILURE;
    if (!initialized_ || goal != goal_) {
      if (initialized_) haltChild();
      goal_ = goal;
      initialized_ = true;
      planned_ = latched_ = false;
    }
    setStatus(BT::NodeStatus::RUNNING);
    // Finish an outstanding plan before latching. Every new goal, including
    // orientation-only goals, must get its own first path.
    if (planned_ && child_node_->status() != BT::NodeStatus::RUNNING) {
      {
        try {
          const auto transform = tf_->lookupTransform(goal.header.frame_id,
            getInput<std::string>("robot_base_frame").value(), tf2::TimePointZero);
          const double distance = std::hypot(transform.transform.translation.x - goal.pose.position.x,
            transform.transform.translation.y - goal.pose.position.y);
          const double radius = getInput<double>("radius").value();
          // Keep small boundary jitter latched, but replan substantial drift so
          // setPlan resets the rotation shim's internal position latch.
          if (latched_ && distance > radius + 0.15) latched_ = false;
          else if (!latched_ && distance <= radius) latched_ = true;
        } catch (const tf2::TransformException &) {
          // Missing TF does not suppress replanning; controller/bridge retain
          // their independent localization and freshness checks.
        }
      }
      if (latched_) return BT::NodeStatus::SUCCESS;
    }
    const auto status = child_node_->executeTick();
    if (status == BT::NodeStatus::SUCCESS) planned_ = true;
    return status;
  }
  std::shared_ptr<tf2_ros::Buffer> tf_;
  geometry_msgs::msg::PoseStamped goal_;
  bool initialized_ = false, planned_ = false, latched_ = false;
};

BT_REGISTER_NODES(factory) {
  factory.registerNodeType<TerminalReplan>("TerminalReplan");
}
