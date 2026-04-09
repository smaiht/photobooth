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

namespace CameraControl
{
    public class PropertyComboBox : System.Windows.Forms.ComboBox
    {
        protected Dictionary<uint, string> map = new Dictionary<uint, string>();

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
            string outString;
            bool isGet = map.TryGetValue(value, out outString);

            if (isGet && !outString.Equals("unknown"))
            {
                if (this.Items.Count == 0)
                {
                    this.Items.Add(outString);
                }
                
                this.SelectedItem = outString;

                if ((string)this.SelectedItem != outString && this.ToString().Contains("AeModeComboBox"))
                {
                    this.Items.Clear();
                    this.Items.Add(outString);
                    this.SelectedItem = outString;
                }
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

            this.Enabled = (desc.NumElements > 1);

            this.Items.Clear();
            {
                for (int i = 0; i < desc.NumElements; i++)
                {
                    string outString;
                    // The character string corresponding to data is acquired.
                    bool isGet = map.TryGetValue((uint)desc.PropDesc[i], out outString);
                    if (isGet && !outString.Equals("unknown"))
                    {
                        // Create list of combo box
                        this.Items.Add(outString);
                    }
                }
            }
        }
    }
}

