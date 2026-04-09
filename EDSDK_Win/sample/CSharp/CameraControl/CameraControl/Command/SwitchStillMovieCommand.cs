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
    class SwitchStillMovieCommand : Command
    {
        private uint _status;

        public SwitchStillMovieCommand(ref CameraModel model, uint status) : base(ref model)
        {
            _status = status;
        }

        // Execute command	
        public override bool Execute()
        {
            uint err = EDSDKLib.EDSDK.EDS_ERR_OK;
            // Get movie mode. Camera hardware is not set to movie.
            if (_model.FixedMovie == 0 && _status == EDSDKLib.EDSDK.CameraCommand_MovieSelectSwOFF)
            {
                return true;
            }

            err = EDSDKLib.EDSDK.EdsSendCommand(_model.Camera, _status, 0);

            if (err == EDSDKLib.EDSDK.EDS_ERR_OK)
            {
                // Set kEdsPropID_SaveTo property to kEdsSaveTo_Camera before changing Movie mode to ON
                if (_status == EDSDKLib.EDSDK.CameraCommand_MovieSelectSwON)
                {
                    // Preservation ahead is set to Camera. 
                    err = EDSDKLib.EDSDK.EdsSetPropertyData(_model.Camera, EDSDKLib.EDSDK.PropID_SaveTo, 0, sizeof(uint), (uint)EDSDKLib.EDSDK.EdsSaveTo.Camera);
                }
                else
                {
                    err = EDSDKLib.EDSDK.EdsSetPropertyData(_model.Camera, EDSDKLib.EDSDK.PropID_SaveTo, 0, sizeof(uint), (uint)EDSDKLib.EDSDK.EdsSaveTo.Host);

                    EDSDKLib.EDSDK.EdsCapacity Capacity;
                    Capacity.NumberOfFreeClusters = 0x7FFFFFFF;
                    Capacity.BytesPerSector = 0x1000;
                    Capacity.Reset = 1;
                    err = EDSDKLib.EDSDK.EdsSetCapacity(_model.Camera, Capacity);
                }
            }

            //Notification of error
            if (err != EDSDKLib.EDSDK.EDS_ERR_OK)
            {
                // It retries it at device busy
                if (err == EDSDKLib.EDSDK.EDS_ERR_DEVICE_BUSY)
                {
                    CameraEvent e = new CameraEvent(CameraEvent.Type.DEVICE_BUSY, IntPtr.Zero);
                    _model.NotifyObservers(e);
                    return true;
                }
                else
                {
                    CameraEvent e = new CameraEvent(CameraEvent.Type.ERROR, (IntPtr)err);
                    _model.NotifyObservers(e);
                    return true;
                }
            }

            return true;
        }
    }
}
