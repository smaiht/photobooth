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
    class ClickAFCommand : Command
    {
        private uint _status;

        public ClickAFCommand(ref CameraModel model, uint status) : base(ref model)
        {
            _status = status;
        }

        // Execute command	
        public override bool Execute()
        {
            //1.Start Live view
            // EvfClickAF is available when the camera is in live view.
            if (!_model.isEvfEnable)
            {
                return true;
            }

            if (_status == 1)
            {
                _model.NotifyObservers(new CameraEvent(CameraEvent.Type.MOUSE_CURSOR, (IntPtr)1));
            }

            uint err = EDSDKLib.EDSDK.EDS_ERR_OK;
            
            if (_status == 2)
            {
                int param = _model.ClickPoint ;
                EDSDKLib.EDSDK.EdsSize AfPoint;
                AfPoint.width = param >> 16;
                AfPoint.height = param & 0xffff;

                err = EDSDKLib.EDSDK.EdsSetFramePoint(_model.Camera, AfPoint, true);
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
