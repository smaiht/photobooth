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
using System.Windows.Forms;

namespace CameraControl
{
    class FormatVolumeCommand : Command
    {
        public FormatVolumeCommand(ref CameraModel model, ref IntPtr volume) : base(ref model) { _volume = volume; }

        private IntPtr _volume;

        public override bool Execute()
        {
            IntPtr camera = _model.Camera;
            uint err = 0;

            //Format the specified SD card
            if (err == EDSDKLib.EDSDK.EDS_ERR_OK)
            {
                if (MessageBox.Show("Format the memory card?", "CameraControl", MessageBoxButtons.OKCancel) == System.Windows.Forms.DialogResult.Cancel)
                {
                    return true;
                }
                if (err == EDSDKLib.EDSDK.EDS_ERR_OK)
                {
                    err = EDSDKLib.EDSDK.EdsFormatVolume(_volume);
                }
            }

            return true;
        }
    }
}
