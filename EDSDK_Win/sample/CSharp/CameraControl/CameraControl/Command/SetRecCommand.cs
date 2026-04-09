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
using System.Runtime.InteropServices;

namespace CameraControl
{
    class SetRecCommand : Command
    {
        private uint _status;

        public SetRecCommand(ref CameraModel model, uint status) : base(ref model)
        {
            _status = status;
        }

        // Execute command	
        public override bool Execute()
        {
            // Start/End movie recording
            if (_model.FixedMovie == 1)
            {
                uint err = EDSDKLib.EDSDK.EdsSetPropertyData(_model.Camera, EDSDKLib.EDSDK.PropID_Record, 0, sizeof(uint), _status);
            }
            if (_status == 0)
            {
                System.Threading.Thread.Sleep(1500);
            }

            return true;
        }
    }
}
