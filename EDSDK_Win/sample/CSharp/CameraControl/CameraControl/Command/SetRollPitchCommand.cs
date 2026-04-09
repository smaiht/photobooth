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
    class SetRollPitchCommand : Command
    {
        private uint _status;

        public SetRollPitchCommand(ref CameraModel model, uint status) : base(ref model)
        {
            _status = status;
        }

        public override bool Execute()
        {
            uint rollPitch = _model.RollPitch;

            if (!_model.isEvfEnable)
            {
                return true;
            }

            uint err = EDSDKLib.EDSDK.EdsSendCommand(_model.Camera, EDSDKLib.EDSDK.CameraCommand_RequestRollPitchLevel, (int)rollPitch);

            if (rollPitch == 1)
            {
                _model.NotifyObservers(new CameraEvent(CameraEvent.Type.ANGLEINFO, IntPtr.Zero));
            }

            //Notification of error
            if (err != EDSDKLib.EDSDK.EDS_ERR_OK)
            {
                // It retries it at device busy
                if (err == EDSDKLib.EDSDK.EDS_ERR_DEVICE_BUSY)
                {
                    CameraEvent e = new CameraEvent(CameraEvent.Type.DEVICE_BUSY, IntPtr.Zero);
                    _model.NotifyObservers(e);
                    return false;
                }

                {
                    CameraEvent e = new CameraEvent(CameraEvent.Type.ERROR, (IntPtr)err);
                    _model.NotifyObservers(e);
                }
            }
            return true;
        }
    }
}
