// Copyright. 2019 - 2026 PSBD. All rights reserved.
//
// FusionCognitive add-on API (v2). Multi-modal cognitive load fusion.
// Requires CapsuleClient built with FusionCognitive support.

#pragma once

#include "CDefinesPrivate.h"
#include "CError.h"
#include "CNFBCalibrator.h"

#ifdef __cplusplus
extern "C" {
#endif

CLC_CLASS_WN(ClassificationFusionCognitivePrivate, clCFusionCognitive);

/**
 * Fusion weights for EEG, PPG, MEMS, and existing classifier outputs.
 * Values are typically in [0, 1]; native may renormalize if sum != 1.
 */
typedef struct clCFusionCognitive_FusionWeights {
    float eegWeight = 0.4F;
    float ppgWeight = 0.2F;
    float memsWeight = 0.1F;
    float classifierWeight = 0.3F;
} clCFusionCognitive_FusionWeights;

typedef struct clCFusionCognitive_Config {
    clCFusionCognitive_FusionWeights fusionWeights;
} clCFusionCognitive_Config;

typedef struct clCFusionCognitive_MetricsV2 {
    int64_t timestampMilli = -1;
    /** Cognitive load index, 0–100 (distinct from clCEmotions_States::cognitiveLoad). */
    float cognitiveLoad = -1.F;
    /** Estimator confidence in [0, 1]. */
    float confidence = -1.F;
    bool hasArtifacts = false;
} clCFusionCognitive_MetricsV2;

typedef struct clCFusionCognitive_BaselinesV2 {
    int64_t timestampMilli = -1;
    float cognitiveLoadBaseline = -1.F;
} clCFusionCognitive_BaselinesV2;

CL_DLL clCFusionCognitive clCFusionCognitive_CreateV2(clCDevice device, clCError* error) NOEXCEPT;
CL_DLL clCFusionCognitive clCFusionCognitive_CreateWithIndividualDataV2(clCDevice device, const clCIndividualNFBData* data, clCError* error) NOEXCEPT;

CL_DLL void clCFusionCognitive_SetConfigV2(clCFusionCognitive fusionCognitive, const clCFusionCognitive_Config* config, clCError* error) NOEXCEPT;
CL_DLL void clCFusionCognitive_GetConfigV2(clCFusionCognitive fusionCognitive, clCFusionCognitive_Config* config, clCError* error) NOEXCEPT;

CL_DLL void clCFusionCognitive_ImportBaselinesV2(clCFusionCognitive fusionCognitive, const clCFusionCognitive_BaselinesV2* baselines, clCError* error) NOEXCEPT;
CL_DLL void clCFusionCognitive_StartBaselineCalibrationV2(clCFusionCognitive fusionCognitive) NOEXCEPT;

typedef void (*clCFusionCognitive_MetricsUpdateHandlerV2)(clCFusionCognitive, const clCFusionCognitive_MetricsV2*) NOEXCEPT;
CL_DLL void clCFusionCognitive_SetOnMetricsUpdateEventV2(clCFusionCognitive fusionCognitive, clCFusionCognitive_MetricsUpdateHandlerV2 handler, clCError* error) NOEXCEPT;

typedef void (*clCFusionCognitive_BaselineCalibratedHandlerV2)(clCFusionCognitive, const clCFusionCognitive_BaselinesV2*) NOEXCEPT;
CL_DLL void clCFusionCognitive_SetOnBaselineUpdateEventV2(clCFusionCognitive fusionCognitive, clCFusionCognitive_BaselineCalibratedHandlerV2 handler, clCError* error) NOEXCEPT;

typedef void (*clCFusionCognitive_CalibrationProgressUpdateHandlerV2)(clCFusionCognitive, float) NOEXCEPT;
CL_DLL void clCFusionCognitive_SetOnCalibrationProgressUpdateEventV2(clCFusionCognitive fusionCognitive, clCFusionCognitive_CalibrationProgressUpdateHandlerV2 handler, clCError* error) NOEXCEPT;

typedef void (*clCFusionCognitive_IndividualNFBUpdateHandlerV2)(clCFusionCognitive) NOEXCEPT;
CL_DLL void clCFusionCognitive_SetOnIndividualNFBUpdateEventV2(clCFusionCognitive fusionCognitive, clCFusionCognitive_IndividualNFBUpdateHandlerV2 handler, clCError* error) NOEXCEPT;

#ifdef __cplusplus
}
#endif
