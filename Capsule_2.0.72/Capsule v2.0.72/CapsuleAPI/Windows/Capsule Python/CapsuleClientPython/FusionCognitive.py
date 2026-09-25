import ctypes
from typing import Callable, List

from Error import Error, Error_Code, CapsuleException
from CapsulePointersImpl import capsule_pointers

# Minimum exports required from CapsuleClient.dll (implement in native per CFusionCognitive.h).
REQUIRED_EXPORTS: List[str] = [
    "clCFusionCognitive_CreateV2",
    "clCFusionCognitive_SetConfigV2",
    "clCFusionCognitive_SetOnMetricsUpdateEventV2",
    "clCFusionCognitive_StartBaselineCalibrationV2",
]


class FusionCognitiveNotSupportedError(RuntimeError):
    """Raised when the loaded DLL does not include FusionCognitive v2 symbols."""

    def __init__(self, lib_path: str, missing: List[str]):
        self.missing = missing
        super().__init__(
            "FusionCognitive v2 is not in this CapsuleClient build. "
            f"Missing exports: {', '.join(missing)}. "
            "Rebuild CapsuleClient.dll from CFusionCognitive.h or use an newer SDK drop. "
            f"Library: {lib_path}".format(lib_path=lib_path)
        )


def missing_exports(lib) -> List[str]:
    return [name for name in REQUIRED_EXPORTS if not hasattr(lib, name)]


def is_available(lib) -> bool:
    return len(missing_exports(lib)) == 0


class FusionCognitive_FusionWeights(ctypes.Structure):
    _fields_ = [
        ("eegWeight", ctypes.c_float),
        ("ppgWeight", ctypes.c_float),
        ("memsWeight", ctypes.c_float),
        ("classifierWeight", ctypes.c_float),
    ]

    def __init__(self, eeg_weight=0.4, ppg_weight=0.2, mems_weight=0.1, classifier_weight=0.3):
        self.eegWeight = eeg_weight
        self.ppgWeight = ppg_weight
        self.memsWeight = mems_weight
        self.classifierWeight = classifier_weight


class FusionCognitive_Config(ctypes.Structure):
    _fields_ = [("fusionWeights", FusionCognitive_FusionWeights)]

    def __init__(self, fusion_weights=None):
        self.fusionWeights = fusion_weights if fusion_weights is not None else FusionCognitive_FusionWeights()


class FusionCognitive_MetricsV2(ctypes.Structure):
    _fields_ = [
        ("timestampMilli", ctypes.c_int64),
        ("cognitiveLoad", ctypes.c_float),
        ("confidence", ctypes.c_float),
        ("hasArtifacts", ctypes.c_bool),
    ]


class FusionCognitive_BaselinesV2(ctypes.Structure):
    _fields_ = [
        ("timestampMilli", ctypes.c_int64),
        ("cognitiveLoadBaseline", ctypes.c_float),
    ]

    def __init__(self, timestamp_milli=-1, cognitive_load_baseline=-1.0):
        self.timestampMilli = timestamp_milli
        self.cognitiveLoadBaseline = cognitive_load_baseline


class FusionCognitive:
    """Multi-modal cognitive load (0–100), v2 add-on API."""

    _name_in_pointers_map = "FusionCognitive"

    def __init__(self, device, lib, individual_nfb_data=None):
        self._lib = lib
        missing = missing_exports(lib)
        if missing:
            raise FusionCognitiveNotSupportedError(getattr(lib, "_name", "CapsuleClient"), missing)

        self._lib.clCFusionCognitive_CreateV2.restype = ctypes.POINTER(ctypes.c_int)
        error = Error()

        if individual_nfb_data is None:
            self._lib.clCFusionCognitive_CreateV2.argtypes = [
                ctypes.POINTER(ctypes.c_int),
                ctypes.POINTER(Error),
            ]
            self._pointer = self._lib.clCFusionCognitive_CreateV2(
                device.get_c_pointer(), ctypes.byref(error)
            )
        else:
            from Calibrator import IndividualNFBData

            self._lib.clCFusionCognitive_CreateWithIndividualDataV2.argtypes = [
                ctypes.POINTER(ctypes.c_int),
                ctypes.POINTER(IndividualNFBData),
                ctypes.POINTER(Error),
            ]
            self._pointer = self._lib.clCFusionCognitive_CreateWithIndividualDataV2(
                device.get_c_pointer(),
                ctypes.byref(individual_nfb_data),
                ctypes.byref(error),
            )

        if error.code is not Error_Code.OK:
            raise CapsuleException(error)

    def set_config(self, config: FusionCognitive_Config):
        self._lib.clCFusionCognitive_SetConfigV2.argtypes = [
            ctypes.POINTER(ctypes.c_int),
            ctypes.POINTER(FusionCognitive_Config),
            ctypes.POINTER(Error),
        ]
        error = Error()
        self._lib.clCFusionCognitive_SetConfigV2(
            self._pointer, ctypes.byref(config), ctypes.byref(error)
        )
        if error.code is not Error_Code.OK:
            raise CapsuleException(error)

    def get_config(self) -> FusionCognitive_Config:
        self._lib.clCFusionCognitive_GetConfigV2.argtypes = [
            ctypes.POINTER(ctypes.c_int),
            ctypes.POINTER(FusionCognitive_Config),
            ctypes.POINTER(Error),
        ]
        config = FusionCognitive_Config()
        error = Error()
        self._lib.clCFusionCognitive_GetConfigV2(
            self._pointer, ctypes.byref(config), ctypes.byref(error)
        )
        if error.code is not Error_Code.OK:
            raise CapsuleException(error)
        return config

    def import_baselines(self, baselines: FusionCognitive_BaselinesV2):
        self._lib.clCFusionCognitive_ImportBaselinesV2.argtypes = [
            ctypes.POINTER(ctypes.c_int),
            ctypes.POINTER(FusionCognitive_BaselinesV2),
            ctypes.POINTER(Error),
        ]
        error = Error()
        self._lib.clCFusionCognitive_ImportBaselinesV2(
            self._pointer, ctypes.byref(baselines), ctypes.byref(error)
        )
        if error.code is not Error_Code.OK:
            raise CapsuleException(error)

    def calibrate_baselines(self):
        self._lib.clCFusionCognitive_StartBaselineCalibrationV2.argtypes = [
            ctypes.POINTER(ctypes.c_int)
        ]
        self._lib.clCFusionCognitive_StartBaselineCalibrationV2(self._pointer)

    def set_on_metrics_update(self, callback: Callable[["FusionCognitive", FusionCognitive_MetricsV2], None]):
        global _fusion_lib_impl, _fusion_metrics_callback
        _fusion_lib_impl = self._lib
        _fusion_metrics_callback = callback
        self.__save_obj()
        error = Error()
        self._lib.clCFusionCognitive_SetOnMetricsUpdateEventV2(
            self._pointer, metrics_impl, ctypes.byref(error)
        )
        if error.code is not Error_Code.OK:
            raise CapsuleException(error)

    def set_on_baseline_update(self, callback: Callable[["FusionCognitive", FusionCognitive_BaselinesV2], None]):
        global _fusion_lib_impl, _fusion_baseline_callback
        _fusion_lib_impl = self._lib
        _fusion_baseline_callback = callback
        self.__save_obj()
        error = Error()
        self._lib.clCFusionCognitive_SetOnBaselineUpdateEventV2(
            self._pointer, baseline_impl, ctypes.byref(error)
        )
        if error.code is not Error_Code.OK:
            raise CapsuleException(error)

    def set_on_calibration_progress(
        self, callback: Callable[["FusionCognitive", float], None]
    ):
        global _fusion_lib_impl, _fusion_calibration_progress_callback
        _fusion_lib_impl = self._lib
        _fusion_calibration_progress_callback = callback
        self.__save_obj()
        error = Error()
        self._lib.clCFusionCognitive_SetOnCalibrationProgressUpdateEventV2(
            self._pointer, calibration_progress_impl, ctypes.byref(error)
        )
        if error.code is not Error_Code.OK:
            raise CapsuleException(error)

    def set_on_individual_nfb(self, callback: Callable[["FusionCognitive"], None]):
        global _fusion_lib_impl, _fusion_nfb_callback
        _fusion_lib_impl = self._lib
        _fusion_nfb_callback = callback
        self.__save_obj()
        error = Error()
        self._lib.clCFusionCognitive_SetOnIndividualNFBUpdateEventV2(
            self._pointer, nfb_impl, ctypes.byref(error)
        )
        if error.code is not Error_Code.OK:
            raise CapsuleException(error)

    def __save_obj(self):
        capsule_pointers[self._name_in_pointers_map] = self


_fusion_lib_impl = None
_fusion_metrics_callback = None
_fusion_baseline_callback = None
_fusion_calibration_progress_callback = None
_fusion_nfb_callback = None


@ctypes.CFUNCTYPE(None, ctypes.POINTER(ctypes.c_int), ctypes.POINTER(FusionCognitive_MetricsV2))
def metrics_impl(_fusion, metrics):
    global _fusion_metrics_callback, capsule_pointers
    _fusion_metrics_callback(capsule_pointers["FusionCognitive"], metrics.contents)


@ctypes.CFUNCTYPE(None, ctypes.POINTER(ctypes.c_int), ctypes.POINTER(FusionCognitive_BaselinesV2))
def baseline_impl(_fusion, baselines):
    global _fusion_baseline_callback, capsule_pointers
    _fusion_baseline_callback(capsule_pointers["FusionCognitive"], baselines.contents)


@ctypes.CFUNCTYPE(None, ctypes.POINTER(ctypes.c_int), ctypes.c_float)
def calibration_progress_impl(_fusion, progress):
    global _fusion_calibration_progress_callback, capsule_pointers
    _fusion_calibration_progress_callback(capsule_pointers["FusionCognitive"], progress)


@ctypes.CFUNCTYPE(None, ctypes.POINTER(ctypes.c_int))
def nfb_impl(_fusion):
    global _fusion_nfb_callback, capsule_pointers
    _fusion_nfb_callback(capsule_pointers["FusionCognitive"])
