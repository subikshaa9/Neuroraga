// Copyright. 2019 - 2026 PSBD. All rights reserved.
//
// V2 extension declarations for existing classifiers (additive; v1 APIs unchanged).
// Implement in native CapsuleClient; mirror in SDKs when each module is ready.

#pragma once

#include "CDefinesPrivate.h"
#include "CError.h"
#include "CProductivity.h"
#include "CPhysiologicalStates.h"
#include "CEmotions.h"
#include "CNFB.h"
#include "CCardio.h"
#include "CPSDData.h"

#ifdef __cplusplus
extern "C" {
#endif

// --- Productivity V2 (example extension; add fields as algorithms evolve) ---

typedef struct clCProductivity_ConfigV2 {
    float metricsSmoothingSec = 1.F;
} clCProductivity_ConfigV2;

typedef struct clCProductivity_MetricsV2 {
    int64_t timestampMilli = -1;
    float fatigueScore = -1.F;
    float reverseFatigueScore = -1.F;
    float gravityScore = -1.F;
    float relaxationScore = -1.F;
    float concentrationScore = -1.F;
    float productivityScore = -1.F;
    float currentValue = -1.F;
    float alpha = -1.F;
    float productivityBaseline = -1.F;
    float accumulatedFatigue = -1.F;
    clCProductivity_FatigueGrowthRate fatigueGrowthRate = clCProductivity_FatigueGrowthRate_None;
    const uint8_t* artifactsData = NULL;
    uint64_t artifactsSize = 0U;
    /** V2-only: estimator confidence in [0, 1]. */
    float confidence = -1.F;
} clCProductivity_MetricsV2;

CL_DLL clCProductivity clCProductivity_CreateV2(clCDevice device, clCError* error) NOEXCEPT;
CL_DLL void clCProductivity_SetConfigV2(clCProductivity productivity, const clCProductivity_ConfigV2* config, clCError* error) NOEXCEPT;

typedef void (*clCProductivity_MetricsUpdateHandlerV2)(clCProductivity, const clCProductivity_MetricsV2*) NOEXCEPT;
CL_DLL void clCProductivity_SetOnMetricsUpdateEventV2(clCProductivity productivity, clCProductivity_MetricsUpdateHandlerV2 handler) NOEXCEPT;

// --- Physiological States V2 ---

typedef struct clCPhysiologicalStates_ConfigV2 {
    float statesSmoothingSec = 1.F;
} clCPhysiologicalStates_ConfigV2;

typedef struct clCPhysiologicalStates_ValueV2 {
    int64_t timestampMilli = -1;
    float relaxation = -1.F;
    float fatigue = -1.F;
    float none = -1.F;
    float concentration = -1.F;
    float involvement = -1.F;
    float stress = -1.F;
    bool nfbArtifacts = false;
    bool cardioArtifacts = false;
    float confidence = -1.F;
} clCPhysiologicalStates_ValueV2;

CL_DLL clCPhysiologicalStates clCPhysiologicalStates_CreateV2(clCDevice device, clCError* error) NOEXCEPT;
CL_DLL void clCPhysiologicalStates_SetConfigV2(clCPhysiologicalStates states, const clCPhysiologicalStates_ConfigV2* config, clCError* error) NOEXCEPT;

typedef void (*clCPhysiologicalStates_StatesUpdateHandlerV2)(clCPhysiologicalStates, const clCPhysiologicalStates_ValueV2*) NOEXCEPT;
CL_DLL void clCPhysiologicalStates_SetOnStatesUpdateEventV2(clCPhysiologicalStates states, clCPhysiologicalStates_StatesUpdateHandlerV2 handler, clCError* error) NOEXCEPT;

// --- Emotions, NFB, Cardio, PSD: declare CreateV2 + SetConfigV2 in native when ready ---

#ifdef __cplusplus
}
#endif
