"""Pluggable trained-image detector. Missing models must never mean missing equipment."""
import importlib


class DetectorNotReady(RuntimeError):
    pass


class CheckedDetector:
    def __init__(self, backend):
        self.backend = backend

    def detect(self, frame, kind):
        result = self.backend.detect(frame, kind)
        if not isinstance(result, tuple) or len(result) != 2:
            raise RuntimeError('检测模块返回格式错误')
        label, evidence = result
        allowed = {'extinguisher'} if kind == 'extinguisher' else {'forward','left','right','uturn'}
        if label is not None and label not in allowed:
            raise RuntimeError('检测类别未映射：'+str(label))
        if not isinstance(evidence, dict):
            raise RuntimeError('检测模块证据格式错误')
        # None means successful inference on a fresh frame with no matching object;
        # exceptions mean inference failure and must abort instead of reporting a missing object.
        return label, evidence


def load_detector(settings):
    if settings.get('backend') == 'reference_test_only':
        from patrol_vision import Detector
        return CheckedDetector(Detector())
    module_name = settings.get('module')
    if not module_name:
        raise DetectorNotReady('训练好的检测模型尚未接入，当前不能开始完整巡检')
    try:
        module = importlib.import_module(module_name)
        backend = module.create_detector(settings)
        if not backend.ready():
            raise DetectorNotReady('检测模块尚未就绪')
        return CheckedDetector(backend)
    except DetectorNotReady:
        raise
    except Exception as exc:
        raise DetectorNotReady('无法加载检测模块：'+str(exc)) from exc
