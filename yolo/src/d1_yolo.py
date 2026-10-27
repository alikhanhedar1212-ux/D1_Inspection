import cv2
from ultralytics import YOLO

model = YOLO('yolov8n.pt')

rtsp_url = "rtsp://192.168.3.100:8554/test?tcp"

cap = cv2.VideoCapture(rtsp_url)
cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)

while True:
    for _ in range(3):
        ret, frame = cap.read()
        if not ret:
            break
    if not ret:
        print("流中断，重连...")
        cap = cv2.VideoCapture(rtsp_url)
        continue

    results = model(frame, classes=[0], verbose=False)
    for r in results:
        for box in r.boxes:
            x1, y1, x2, y2 = box.xyxy[0].tolist()
            conf = float(box.conf[0])
            cv2.rectangle(frame, (int(x1), int(y1)), (int(x2), int(y2)), (0, 255, 0), 2)
            cv2.putText(frame, f'person {conf:.2f}', (int(x1), int(y1)-10),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)

    cv2.imshow('YOLO on Go2', frame)
    if cv2.waitKey(1) & 0xFF == ord('q'):
        break

cap.release()
cv2.destroyAllWindows()
