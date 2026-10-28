// Passive native battery reader. No publishers or power-control commands.
#include <ecal/ecal.h>
#include <ecal/msg/protobuf/dynamic_json_subscriber.h>
#include <chrono>
#include <iostream>
#include <mutex>
#include <string>
#include <thread>

int main(int argc, char** argv) {
  using Clock = std::chrono::steady_clock;
  eCAL::Initialize(argc, argv, "voice_battery_read_only",
                   eCAL::Init::Subscriber | eCAL::Init::ProcessReg);
  std::mutex lock;
  std::string latest;
  unsigned count = 0;
  Clock::time_point received{};
  int result = 1;
  {
    eCAL::protobuf::CDynamicJSONSubscriber subscriber("battery_state");
    subscriber.AddReceiveCallback([&](const char*, const eCAL::SReceiveCallbackData* data) {
      std::lock_guard<std::mutex> guard(lock);
      latest.assign(static_cast<const char*>(data->buf), data->size);
      received = Clock::now();
      ++count;
    });
    const auto started = Clock::now();
    while (std::chrono::duration<double>(Clock::now()-started).count() < 7) {
      {
        std::lock_guard<std::mutex> guard(lock);
        if (count >= 2 && !latest.empty()) {
          const auto age = std::chrono::duration<double>(Clock::now()-received).count();
          std::cout << "{\"source\":\"battery_state\",\"received_count\":" << count
                    << ",\"sample_age_s\":" << age << ",\"battery\":" << latest << "}" << std::endl;
          result = 0;
          break;
        }
      }
      std::this_thread::sleep_for(std::chrono::milliseconds(20));
    }
    if (result) std::cerr << "未收到新的电池状态" << std::endl;
  }
  eCAL::Finalize();
  return result;
}
