// Copyright. 2019 - 2024 PSBD. All rights reserved.

using System;
using System.Runtime.InteropServices;
using static Capsule.Utility.Converter;

namespace Capsule.Utility
{
    /**
    * \brief Handler adapter for events.
    */
    public interface IHandlerAdapter
    {
        void Attach<T>(T obj, [Optional] object deviceObj);
        object Map(Handler<DeviceLocator> handler);
    }

    /**
     * \brief Default handler adapter.
     */
    public sealed class DefaultHandlerAdapter : IHandlerAdapter
    {
        private static T? FromPtr<T>(IntPtr ptr)
        {
            return Marshal.PtrToStructure<T>(ptr);
        }

        public void Attach<T>(T obj, [Optional] object deviceObj)
        {
            switch (obj)
            {
                case DeviceLocator locator:
                {
                    locator.SetDeviceListHandler((ptr, dPtr, err) =>
                    {
                        var l = GetObjectFromPtr<DeviceLocator>(ptr);
                        if (l == null) return;
                        l.OnDeviceListEvent?.Invoke(l, DeviceInfoInternal.ConvertDeviceInfoList(dPtr), err);
                    });
                    break;
                }
                case Device device:
                {
                    device.SetConnectionStatusChangedHandler((ptr, connected) =>
                    {
                        var d = GetObjectFromPtr<Device>(ptr);
                        if (d == null) return;
                        d.OnConnectionStatusChangedEvent?.Invoke(d, connected);
                    });
                    device.SetResistanceUpdateHandler((ptr, resistance) =>
                    {
                        var d = GetObjectFromPtr<Device>(ptr);
                        if (d == null) return;
                        d.OnResistanceUpdateEvent?.Invoke(d, ResistanceInternal.ConvertResistance(resistance));
                    });
                    device.SetModeSwitchedHandler((ptr, mode) =>
                    {
                        var d = GetObjectFromPtr<Device>(ptr);
                        if (d == null) return;
                        d.OnModeSwitchedEvent?.Invoke(d, mode);
                    });
                    device.SetErrorHandler((ptr, error) => {
                        var d = GetObjectFromPtr<Device>(ptr);
                        if (d == null) return;
                        d.OnErrorEvent?.Invoke(d, error);
                    });
                    device.SetEegDataHandler((ptr, eeg) => {
                        var d = GetObjectFromPtr<Device>(ptr);
                        if (d == null) return;
                        try
                        {
                            d.EegDataCurrent = EegDataInternal.ConvertEegData(eeg);
                            d.OnEegDataEvent?.Invoke(d, d.EegDataCurrent);
                        }
                        catch (CapsuleException ex)
                        {
                            System.Diagnostics.Debug.WriteLine($"Failed to convert eeg data: {ex.Message}");
                        }
                    });
                    device.SetPsdDataHandler((ptr, psd) =>
                    {
                        var d = GetObjectFromPtr<Device>(ptr);
                        if (d == null) return;
                        try
                        {
                            d.PsdDataCurrent = PsdDataInternal.ConvertPsdData(psd);
                            d.OnPsdDataEvent?.Invoke(d, d.PsdDataCurrent);
                        }
                        catch (CapsuleException ex)
                        {
                            System.Diagnostics.Debug.WriteLine($"Failed to convert psd data: {ex.Message}");
                        }
                    });
                    device.SetEegArtifactsHandler((ptr, eegArtifacts) =>
                    {
                        var d = GetObjectFromPtr<Device>(ptr);
                        if (d == null) return;
                        try
                        {
                            d._EegArtifacts = EegArtifactsInternal.ConvertEegArtifacts(eegArtifacts);
                            d.OnEegArtifactsEvent?.Invoke(d, d._EegArtifacts);
                        }
                        catch (CapsuleException ex)
                        {
                            System.Diagnostics.Debug.WriteLine($"Failed to convert eeg artifacts: {ex.Message}");
                        }
                    });
                    device.SetBatteryChargeUpdateHandler((ptr, charge) =>
                    {
                        var d = GetObjectFromPtr<Device>(ptr);
                        if (d == null) return;
                        d.OnBatteryChargeUpdateEvent?.Invoke(d, charge);
                    });
                    break;
                }
                case Nfb nfb:
                {
                    nfb.SetUserStateChangedHandler((ptr, statePtr) =>
                    {
                        var c = GetObjectFromPtr<Nfb>(ptr);
                        if (c == null) return;
                        c.OnUserStateChangedEvent?.Invoke(c, FromPtr<Nfb.UserState>(statePtr));
                    });
                    nfb.SetErrorHandler((ptr, errorPtr) =>
                    {
                        var c = GetObjectFromPtr<Nfb>(ptr);
                        if (c == null) return;
                        c.OnErrorEvent?.Invoke(c, errorPtr);
                    });
                    break;
                }
                case Calibrator calibrator:
                {
                    calibrator.SetIndividualNfbStageFinishedHandler(ptr =>
                    {
                        var c = GetObjectFromPtr<Calibrator>(ptr);
                        if (c == null) return;
                        c.OnIndividualNfbStageFinishedEvent?.Invoke(c);
                    });
                    calibrator.SetCalibratedHandler((ptr, nfbPtr) =>
                    {
                        var c = GetObjectFromPtr<Calibrator>(ptr);
                        if (c == null) return;
                        c.OnCalibratedEvent?.Invoke(c, FromPtr<Calibrator.IndividualNfbData>(nfbPtr));
                    });
                    break;
                }
                case Productivity productivity:
                {
                    productivity.SetBaselineUpdateHandler((ptr, baselinesPtr) =>
                    {
                        var c = GetObjectFromPtr<Productivity>(ptr);
                        if (c == null) return;
                        c.OnBaselineUpdateEvent?.Invoke(c, FromPtr<Productivity.Baselines>(baselinesPtr));
                    });
                    productivity.SetIndexesHandler((ptr, indexesPtr) =>
                    {
                        var c = GetObjectFromPtr<Productivity>(ptr);
                        if (c == null) return;
                        c.OnIndexesEvent?.Invoke(c, FromPtr<Productivity.Indexes>(indexesPtr));
                    });

                    productivity.SetMetricsUpdateHandler((ptr, metricsPtr) =>
                    {
                        var c = GetObjectFromPtr<Productivity>(ptr);
                        if (c == null) return;
                        c.OnMetricsUpdateEvent?.Invoke(c, new Productivity.Metrics(FromPtr<Productivity.MetricsInternal>(metricsPtr)));
                    });
                    productivity.SetCalibrationProgressUpdateHandler((ptr, values) =>
                    {
                        var c = GetObjectFromPtr<Productivity>(ptr);
                        if (c == null) return;
                        c.OnCalibrationProgressUpdateEvent?.Invoke(c, values);
                    });
                    productivity.SetIndividualNFBUpdateHandler((ptr) =>
                    {
                        var c = GetObjectFromPtr<Productivity>(ptr);
                        if (c == null) return;
                        c.OnIndividualNFBUpdateEvent?.Invoke(c);
                    });
                    break;
                }
                case Cardio cardio:
                {
                    Error error = new();
                    cardio.SetIndexesUpdateHandler((ptr, indexesPtr) =>
                    {
                        var c = GetObjectFromPtr<Cardio>(ptr);
                        if (c == null) return;
                        c.OnIndexesUpdateEvent?.Invoke(c, FromPtr<Cardio.CardioData>(indexesPtr));
                    }, ref error);
                    cardio.SetCalibratedHandler((ptr) =>
                    {
                        var c = GetObjectFromPtr<Cardio>(ptr);
                        if (c == null) return;
                        c.OnCalibratedEvent?.Invoke(c);
                    }, ref error);
                    Device dv = (Device)deviceObj;
                    cardio.SetPPGDataHandler((ptr, ppg) => {
                        var c = GetObjectFromPtr<Cardio>(ptr);
                        if (c == null) return;
                        try {
                            c.PPGDataCurrent = PPGDataInternal.ConvertPPGData(ppg);
                            c.OnPPGDataEvent?.Invoke(c, c.PPGDataCurrent);
                        }
                        catch (CapsuleException ex)
                        {
                            System.Diagnostics.Debug.WriteLine($"Failed to convert eeg artifacts: {ex.Message}");
                        }
                    }, ref error);
                    break;
                }
                case Emotions emotions:
                {
                    emotions.SetErrorHandler((ptr, errorPtr) =>
                    {
                        var c = GetObjectFromPtr<Emotions>(ptr);
                        if (c == null) return;
                        c.OnErrorEvent?.Invoke(c, errorPtr);
                    });
                    emotions.SetEmotionsStateDelegateFloatHandler((ptr, statesPtr) =>
                    {
                        var c = GetObjectFromPtr<Emotions>(ptr);
                        if (c == null) return;
                        c.OnEmotionalStatesUpdateEvent?.Invoke(c, FromPtr<Emotions.EmotionalStates>(statesPtr));
                    });
                    break;
                }
                case PhysiologicalStates states:
                {
                    Error error = new();
                    states.SetPSCalibratedHandler((ptr, baselinesPtr) =>
                    {
                        var c = GetObjectFromPtr<PhysiologicalStates>(ptr);
                        if (c == null) return;
                        c.OnPhysiologicalStatesCalibratedEvent?.Invoke(c, FromPtr<PhysiologicalStates.PhysiologicalStatesBaselines>(baselinesPtr));
                    }, ref error);
                    states.SetPSUpdateHandler((ptr, statesPtr) =>
                    {
                        var c = GetObjectFromPtr<PhysiologicalStates>(ptr);
                        if (c == null) return;
                        c.OnPhysiologicalStatesUpdateEvent?.Invoke(c, FromPtr<PhysiologicalStates.PhysiologicalStatesValue>(statesPtr));
                    }, ref error);
                    states.SetPSCalibrationProgressUpdateHandler((ptr, progress) =>
                    {
                        var c = GetObjectFromPtr<PhysiologicalStates>(ptr);
                        if (c == null) return;
                        c.OnCalibrationProgressUpdateEvent?.Invoke(c, progress);
                    }, ref error);
                    states.SetPSIndividualNFBUpdateHandler((ptr) =>
                    {
                        var c = GetObjectFromPtr<PhysiologicalStates>(ptr);
                        if (c == null) return;
                        c.OnIndividualNFBUpdateEvent?.Invoke(c);
                    }, ref error);
                    break;
                }
                case MEMS MEMSData:
                {
                    Error error = new();
                    MEMSData.SetMEMSDataHandler((ptr, memsData) =>
                    {
                        var mems = GetObjectFromPtr<MEMS>(ptr);
                        if (mems == null) return;
                        mems.MEMSDataCurrent = MEMSDataIternal.ConvertMEMSData(memsData);
                        mems.OnMEMSDataEvent?.Invoke(mems, mems.MEMSDataCurrent);
                    }, ref error);
                    break;
                }
            }
        }

        public static IHandlerAdapter Adapter() => new DefaultHandlerAdapter();

        public object Map(Handler<DeviceLocator> handler)
        {
            HandlerCallback lambda = ptr =>
            {
                var c = GetObjectFromPtr<DeviceLocator>(ptr);
                if (c != null)
                {
                    handler(c);
                }
            };
            return lambda;
        }
    }
}