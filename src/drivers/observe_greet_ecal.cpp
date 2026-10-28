// Passive observation of the native command and state channels.
#include <ecal/ecal.h>
#include <ecal/msg/protobuf/dynamic_json_subscriber.h>
#include <chrono>
#include <iostream>
#include <memory>
#include <mutex>
#include <thread>
#include <vector>

int main(int argc, char** argv) {
  eCAL::Initialize(argc, argv, "greet_native_read_only",
                   eCAL::Init::Subscriber | eCAL::Init::ProcessReg);
  std::mutex mutex;
  const auto start = std::chrono::steady_clock::now();
  std::vector<std::unique_ptr<eCAL::protobuf::CDynamicJSONSubscriber>> subscriptions;
  for (const char* topic : {"app_cmd", "app_state", "sdk_cmd", "sdk_robotstate"}) {
    auto sub = std::make_unique<eCAL::protobuf::CDynamicJSONSubscriber>(topic);
    sub->AddReceiveCallback([&, topic](const char*, const eCAL::SReceiveCallbackData* data) {
      const double elapsed = std::chrono::duration<double>(
          std::chrono::steady_clock::now() - start).count();
      std::lock_guard<std::mutex> lock(mutex);
      std::cout << "{\"elapsed\":" << elapsed << ",\"topic\":\"" << topic
                << "\",\"data\":" << std::string(static_cast<const char*>(data->buf), data->size)
                << "}" << std::endl;
    });
    subscriptions.push_back(std::move(sub));
  }
  std::cout << "{\"observer\":\"ready\",\"duration_seconds\":900}" << std::endl;
  std::this_thread::sleep_for(std::chrono::seconds(900));
  subscriptions.clear();
  eCAL::Finalize();
}
