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
    class SwitchMirrorUpCommand : Command
    {
        private uint _status;

        public SwitchMirrorUpCommand(ref CameraModel model, uint status) : base(ref model)
        {
            _status = status;
        }

        // Execute command	
        public override bool Execute()
        {
            uint err = EDSDKLib.EDSDK.EDS_ERR_OK;

            if (_model.MirrorLockUpState == (uint)EDSDKLib.EDSDK.EdsMirrorLockupState.DuringShooting || _model.isEvfEnable || _model.FixedMovie != 0)
            {
                return true;
            }

            // Mirror up ON
            if (_status == 1 && _model.MirrorLockUpState == (uint)EDSDKLib.EDSDK.EdsMirrorLockupState.Disable)
            {
                // mirrorUpSetting 1 : ON
                uint mirrorUpSetting = (uint)EDSDKLib.EDSDK.EdsMirrorUpSetting.On;
                // Set Mirror Up Setting.
                err = EDSDKLib.EDSDK.EdsSetPropertyData(_model.Camera, EDSDKLib.EDSDK.PropID_MirrorUpSetting, 0, sizeof(uint), mirrorUpSetting);
            }
            // Mirror up OFF
            else if (_status == 0 && _model.MirrorLockUpState == (uint)EDSDKLib.EDSDK.EdsMirrorLockupState.Enable)
            {
                // mirrorUpSetting 0 : OFF
                uint mirrorUpSetting = (uint)EDSDKLib.EDSDK.EdsMirrorUpSetting.Off;
                // Set Mirror Up Setting.
                err = EDSDKLib.EDSDK.EdsSetPropertyData(_model.Camera, EDSDKLib.EDSDK.PropID_MirrorUpSetting, 0, sizeof(uint), mirrorUpSetting);
            }
            else
            {
                //NOP
            }

            return true;
        }
    }
}
