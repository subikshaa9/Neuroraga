# FusionCognitive add-on (v2)

## Requirements summary (from product Q&A)

| Topic | Decision |
|--------|----------|
| Scope | New **FusionCognitive** module + **V2** extensions on existing classifiers |
| Native | Full stack — implement in `CapsuleClient` then mirror headers/SDK |
| SDK (phase 1) | **Python only** |
| Inputs | EEG, PPG, MEMS, Cardio, Productivity/PhysiologicalStates, fusion |
| Calibration | **New baseline** (`FusionCognitive_BaselinesV2`) + closed-eyes NFB (same as Productivity) |
| Config | `SetConfigV2` with **fusion weights** (EEG / PPG / MEMS / classifiers) |
| Compatibility | **Versioned** — `*V2` symbols; v1 APIs unchanged |
| Devices | **Headphones**, **Band** |
| Template metric | **Cognitive load** 0–100, update at **EEG packet rate** |

## Native implementation checklist

1. `ClassificationFusionCognitivePrivate` — subscribe to EEG, PPG, MEMS, Productivity, PhysiologicalStates, Cardio, PSD/artifacts.
2. On each EEG packet (or internal tick aligned to EEG), compute `cognitiveLoad` ∈ [0, 100] and `confidence` ∈ [0, 1].
3. Gate on artifacts; set `hasArtifacts` when fusion inputs are unreliable.
4. `StartBaselineCalibrationV2` — collect `cognitiveLoadBaseline` over a session window (duration TBD, suggest 60–120 s).
5. Honor `clCFusionCognitive_Config::fusionWeights` (renormalize if needed).
6. Export all symbols in `CFusionCognitive.h`.

## Python usage

```python
from FusionCognitive import (
    FusionCognitive,
    FusionCognitive_Config,
    FusionCognitive_FusionWeights,
    FusionCognitive_MetricsV2,
)

fusion = FusionCognitive(device, lib)
fusion.set_config(FusionCognitive_Config(
    FusionCognitive_FusionWeights(eeg_weight=0.5, ppg_weight=0.15, mems_weight=0.1, classifier_weight=0.25)
))
fusion.set_on_metrics_update(on_fusion_metrics)
# After calibrator + device.start():
fusion.calibrate_baselines()
```

## V2 extensions on existing modules

See `Include/CapsuleApiV2Extensions.h`. Productivity and PhysiologicalStates V2 structs are drafted; Emotions/NFB/Cardio/PSD need matching native work.

## DLL note — why you see `function 'clCFusionCognitive_CreateV2' not found`

The **Python wrapper and `CFusionCognitive.h` header are only the contract**. Your current `CapsuleClient.dll` (v2.0.72) was built **before** FusionCognitive existed, so Windows cannot load those exports.

**What works today without rebuilding:** Emotions, Productivity, Physiological States, Cardio, EEG, etc.

**What requires a new native build:**

1. Implement `ClassificationFusionCognitivePrivate` in the CapsuleClient C++ codebase.
2. Export every symbol listed in `Include/CFusionCognitive.h` (at minimum `REQUIRED_EXPORTS` in `FusionCognitive.py`).
3. Replace `CapsuleClient.dll` next to `capsule_metrics_gui.py`.
4. Restart the GUI — log should show `FusionCognitive v2: found in DLL.`

**Quick check (PowerShell, from folder containing the DLL):**

```powershell
dumpbin /exports CapsuleClient.dll | findstr FusionCognitive
```

If nothing is listed, the DLL does not include the add-on yet.

The metrics GUI checks exports at **Load library** and skips FusionCognitive cleanly so the rest of the session still runs.
