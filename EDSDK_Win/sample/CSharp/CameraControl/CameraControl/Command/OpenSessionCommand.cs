/******************************************************************************
*                                                                             *
*   PROJECT : Eos Digital camera Software Development Kit EDSDK               *
*                                                                             *
*   Description: This is the Sample code to show the usage of EDSDK.          *
*                                                                             *
*                                                                             *
*******************************************************************************
*                                                                             *
*   Written and developed by Canon Inc.                                       *
*   Copyright Canon Inc. 2018 All Rights Reserved                             *
*                                                                             *
*******************************************************************************/

using System;

namespace CameraControl
{
    class OpenSessionCommand : Command
    {
        public OpenSessionCommand(ref CameraModel model) : base(ref model) { }

        public override bool Execute()
        {
            //Enabling private properties
            uint err = EDSDKLib.EDSDK.EDS_ERR_OK;
            err = EDSDKLib.EDSDK.EdsSetPropertyData(_model.Camera, 0x01000000, 0x14840DF1, sizeof(uint), EDSDKLib.EDSDK.PropID_TempStatus);
            err = EDSDKLib.EDSDK.EdsSetPropertyData(_model.Camera, 0x01000000, 0x05B3740D, sizeof(uint), EDSDKLib.EDSDK.PropID_Evf_RollingPitching);
            err = EDSDKLib.EDSDK.EdsSetPropertyData(_model.Camera, 0x01000000, 0x17AF25B1, sizeof(uint), EDSDKLib.EDSDK.PropID_FixedMovie);
            err = EDSDKLib.EDSDK.EdsSetPropertyData(_model.Camera, 0x01000000, 0x2A0C1274, sizeof(uint), EDSDKLib.EDSDK.PropID_MovieParam);
            err = EDSDKLib.EDSDK.EdsSetPropertyData(_model.Camera, 0x01000000, 0x3FB1718B, sizeof(uint), EDSDKLib.EDSDK.PropID_Aspect);
            err = EDSDKLib.EDSDK.EdsSetPropertyData(_model.Camera, 0x01000000, 0x653048A9, sizeof(uint), EDSDKLib.EDSDK.PropID_Evf_ClickWBCoeffs);
            err = EDSDKLib.EDSDK.EdsSetPropertyData(_model.Camera, 0x01000000, 0x4D2879F3, sizeof(uint), EDSDKLib.EDSDK.PropID_Evf_VisibleRect);
            err = EDSDKLib.EDSDK.EdsSetPropertyData(_model.Camera, 0x01000000, 0x20DD3609, sizeof(uint), EDSDKLib.EDSDK.PropID_ManualWhiteBalanceData);
            err = EDSDKLib.EDSDK.EdsSetPropertyData(_model.Camera, 0x01000000, 0x517F095D, sizeof(uint), EDSDKLib.EDSDK.PropID_MirrorUpSetting);
            err = EDSDKLib.EDSDK.EdsSetPropertyData(_model.Camera, 0x01000000, 0x00E13499, sizeof(uint), EDSDKLib.EDSDK.PropID_MirrorLockUpState);
            err = EDSDKLib.EDSDK.EdsSetPropertyData(_model.Camera, 0x01000000, 0x51DD2696, sizeof(uint), EDSDKLib.EDSDK.PropID_UTCTime);
            err = EDSDKLib.EDSDK.EdsSetPropertyData(_model.Camera, 0x01000000, 0x00FA71F7, sizeof(uint), EDSDKLib.EDSDK.PropID_TimeZone);
            err = EDSDKLib.EDSDK.EdsSetPropertyData(_model.Camera, 0x01000000, 0x09780670, sizeof(uint), EDSDKLib.EDSDK.PropID_SummerTimeSetting);
            err = EDSDKLib.EDSDK.EdsSetPropertyData(_model.Camera, 0x01000000, 0x1C31565B, sizeof(uint), EDSDKLib.EDSDK.PropID_AutoPowerOffSetting);
            err = EDSDKLib.EDSDK.EdsSetPropertyData(_model.Camera, 0x01000000, 0x1EDD16B6, sizeof(uint), EDSDKLib.EDSDK.PropID_StillMovieDivideSetting);
            err = EDSDKLib.EDSDK.EdsSetPropertyData(_model.Camera, 0x01000000, 0x4FB44E3C, sizeof(uint), EDSDKLib.EDSDK.PropID_CardExtension);
            err = EDSDKLib.EDSDK.EdsSetPropertyData(_model.Camera, 0x01000000, 0x5C6C20B2, sizeof(uint), EDSDKLib.EDSDK.PropID_MovieCardExtension);
            err = EDSDKLib.EDSDK.EdsSetPropertyData(_model.Camera, 0x01000000, 0x139E4D1D, sizeof(uint), EDSDKLib.EDSDK.PropID_StillCurrentMedia);
            err = EDSDKLib.EDSDK.EdsSetPropertyData(_model.Camera, 0x01000000, 0x00D50906, sizeof(uint), EDSDKLib.EDSDK.PropID_MovieCurrentMedia);
            err = EDSDKLib.EDSDK.EdsSetPropertyData(_model.Camera, 0x01000000, 0x707571DF, sizeof(uint), EDSDKLib.EDSDK.PropID_FocusShiftSetting);
            err = EDSDKLib.EDSDK.EdsSetPropertyData(_model.Camera, 0x01000000, 0x44396197, sizeof(uint), EDSDKLib.EDSDK.PropID_MovieHFRSetting);


            //The communication with the camera begins
            err = EDSDKLib.EDSDK.EdsOpenSession(_model.Camera);

            if (err == EDSDKLib.EDSDK.EDS_ERR_OK)
            {
                uint outPropertyData;
                err = EDSDKLib.EDSDK.EdsGetPropertyData(_model.Camera, EDSDKLib.EDSDK.PropID_FixedMovie, 0, out outPropertyData);

                if (outPropertyData == 0)
                {
                    err = EDSDKLib.EDSDK.EdsSetPropertyData(_model.Camera, EDSDKLib.EDSDK.PropID_SaveTo, 0, sizeof(uint), (uint)EDSDKLib.EDSDK.EdsSaveTo.Host);
                    if (err == EDSDKLib.EDSDK.EDS_ERR_OK)
                    {
                        EDSDKLib.EDSDK.EdsCapacity Capacity;
                        Capacity.NumberOfFreeClusters = 0x7FFFFFFF;
                        Capacity.BytesPerSector = 0x1000;
                        Capacity.Reset = 1;
                        err = EDSDKLib.EDSDK.EdsSetCapacity(_model.Camera, Capacity);
                    }
                }
                else
                {
                    err = EDSDKLib.EDSDK.EdsSetPropertyData(_model.Camera, EDSDKLib.EDSDK.PropID_SaveTo, 0, sizeof(uint), (uint)EDSDKLib.EDSDK.EdsSaveTo.Camera);
                }
            }

            //Notification of error
            if (err != EDSDKLib.EDSDK.EDS_ERR_OK)
            {
                CameraEvent e = new CameraEvent(CameraEvent.Type.ERROR, (IntPtr)err);
                _model.NotifyObservers(e);
            }

            return true;
        }
    }
}
