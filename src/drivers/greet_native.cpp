// XG greeting through the same AppCmd channel observed during RB+Y.
#include <ecal/ecal.h>
#include <ecal/msg/protobuf/subscriber.h>
#include <ecal/msg/protobuf/publisher.h>
#include <robot_sdk.pb.h>
#include <chrono>
#include <cmath>
#include <iostream>
#include <mutex>
#include <thread>
#include <string>

using Clock = std::chrono::steady_clock;
using State = robot_sdk::pb::AppState;
double age(Clock::time_point t) {
  return std::chrono::duration<double>(Clock::now()-t).count();
}
bool stationary(const State& s) {
  if (s.v_body_size()!=3 || s.gyro_size()!=3) return false;
  for (int i=0;i<3;++i) {
    if (!std::isfinite(s.v_body(i)) || std::abs(s.v_body(i))>=.05f ||
        !std::isfinite(s.gyro(i)) || std::abs(s.gyro(i))>=.10f) return false;
  }
  return true;
}
bool ready(const State& s) {
  // Observed hand-controller standing state in laboratory mode.
  if (s.cur_ctrl_mode()!=18 || s.cur_motion_mode()!=1 || !stationary(s) ||
      s.position_size()!=3 || s.rpy_size()!=3) return false;
  return std::isfinite(s.position(2)) && s.position(2)>.20f && s.position(2)<.45f &&
      std::isfinite(s.rpy(0)) && std::abs(s.rpy(0))<.20f &&
      std::isfinite(s.rpy(1)) && std::abs(s.rpy(1))<.20f;
}
int main(int argc, char** argv) {
  const bool check = argc==2 && std::string(argv[1])=="--check";
  if (argc==2 && std::string(argv[1])=="--self-test") {
    State s; s.set_cur_ctrl_mode(18); s.set_cur_motion_mode(1);
    for(int i=0;i<3;++i) {s.add_v_body(0);s.add_gyro(0);s.add_position(i==2?.32f:0);s.add_rpy(0);}
    bool ok=ready(s);
    s.set_cur_ctrl_mode(1);ok=ok&&!ready(s);s.set_cur_ctrl_mode(18);
    s.set_v_body(0,.1f);ok=ok&&!ready(s);s.set_v_body(0,0);
    s.set_rpy(1,.4f);ok=ok&&!ready(s);s.set_rpy(1,0);
    s.set_position(2,.05f);ok=ok&&!ready(s);s.set_position(2,.32f);
    s.set_gyro(0,NAN);ok=ok&&!ready(s);s.set_gyro(0,0);
    s.clear_v_body();ok=ok&&!ready(s);
    std::cout << (ok?"guard tests passed":"guard tests failed") << std::endl;
    return ok?0:1;
  }
  if(argc!=1 && !check) return 2;
  eCAL::Initialize(argc,argv,"voice_greet_xg",eCAL::Init::Subscriber|eCAL::Init::ProcessReg|
      (check?0:eCAL::Init::Publisher));
  int result=1;
  {
    std::mutex mutex; State latest; Clock::time_point received{};
    eCAL::protobuf::CSubscriber<State> sub("app_state");
    sub.AddReceiveCallback([&](const char*,const State& s,long long,long long,long long){
      std::lock_guard<std::mutex> lock(mutex);latest=s;received=Clock::now();
    });
    auto snapshot=[&]() { std::lock_guard<std::mutex> lock(mutex);return std::make_pair(latest,received); };
    auto start=Clock::now(); Clock::time_point quiet{};
    bool eligible=false;
    while(age(start)<5) {
      auto [s,t]=snapshot();
      if(age(t)<.3 && ready(s)) {
        if(quiet==Clock::time_point{}) quiet=Clock::now();
        if(age(quiet)>=.5) {eligible=true;break;}
      } else quiet={};
      std::this_thread::sleep_for(std::chrono::milliseconds(10));
    }
    if(!eligible) {
      std::cerr << "请先手柄进入实验室模式并站稳；本体状态或姿态检查未通过" << std::endl;
    } else if(check) {
      std::cout << "{\"checked\":true,\"native_ready\":true,\"control_mode\":18,\"motion_mode\":1}" << std::endl;
      result=0;
    } else {
      eCAL::protobuf::CPublisher<robot_sdk::pb::AppCmd> pub("app_cmd");
      // Allow subscriber discovery before the bounded command burst.
      std::this_thread::sleep_for(std::chrono::milliseconds(1000));
      auto [before,stamp]=snapshot();
      if(age(stamp)>=.3 || !ready(before)) {
        std::cerr << "发送前状态改变，未发送动作" << std::endl;
      } else {
        robot_sdk::pb::AppCmd command;command.set_control_mode(1);command.set_motion_mode(11);
        bool entered=false;auto sent=Clock::now();
        while(age(sent)<1.5) {
          auto [s,t]=snapshot();
          if(age(t)>=.3) break;
          if(s.cur_ctrl_mode()==1 && s.cur_motion_mode()==11) {entered=true;break;}
          if(!ready(s)) break;
          pub.Send(command);
          std::this_thread::sleep_for(std::chrono::milliseconds(10));
        }
        // Release the command once acknowledged; never send stand/lie/lab mode commands.
        std::cout << "{\"action\":\"greet\",\"transport\":\"app_cmd\",\"entered_greet\":"
                  << (entered?"true":"false") << "}" << std::endl;
        if(entered) {
          Clock::time_point settled{};bool saw_return=false;
          while(age(sent)<16) {
            auto [s,t]=snapshot();
            if(age(t)>=.3) break;
            if(s.cur_ctrl_mode()==18 && s.cur_motion_mode()==1) saw_return=true;
            if(saw_return && ready(s)) {
              if(settled==Clock::time_point{}) settled=Clock::now();
              if(age(settled)>=.5) {result=0;break;}
            } else settled={};
            if(!((s.cur_ctrl_mode()==1 && (s.cur_motion_mode()==11 || s.cur_motion_mode()==10)) ||
                 (s.cur_ctrl_mode()==18 && s.cur_motion_mode()==1))) break;
            std::this_thread::sleep_for(std::chrono::milliseconds(10));
          }
        }
        std::cout << "{\"action\":\"greet\",\"entered_greet\":" << (entered?"true":"false")
                  << ",\"returned_to_stand\":" << (result==0?"true":"false")
                  << ",\"duration\":" << age(sent) << "}" << std::endl;
        if(result) std::cerr << "未确认打招呼状态进入并返回站立；不自动重试" << std::endl;
      }
    }
  }
  eCAL::Finalize(); return result;
}
