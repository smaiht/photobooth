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
using System.Collections.Generic;
using System.Linq;
using System.Text;
using System.Threading.Tasks;

namespace CameraControl
{
    public class PropertyTrackBar : System.Windows.Forms.TrackBar
    {

        private delegate void _UpdateProperty(uint value);

        protected void UpdateProperty(uint value)
        {
            if (this.InvokeRequired)
            {
                //The update processing can be executed from another thread. 
                this.Invoke(new _UpdateProperty(UpdateProperty), new object[] { value });
                return;
            }

            // The character string corresponding to data is acquired. 
            if (this.CanSelect)
            {
                this.Value = (int)value;
            }
        }

        private delegate void _UpdatePropertyDesc(ref EDSDKLib.EDSDK.EdsPropertyDesc desc);

        protected void UpdatePropertyDesc(ref EDSDKLib.EDSDK.EdsPropertyDesc desc)
        {
            if (this.InvokeRequired)
            {
                //The update processing can be executed from another thread. 
                this.Invoke(new _UpdatePropertyDesc(UpdatePropertyDesc), new object[] { desc });
                return;
            }

            this.Enabled = (desc.NumElements != 0);

            if (desc.NumElements != 0)
            {
                this.Maximum = desc.PropDesc[0] - 1;
            }
        }
    }
}
