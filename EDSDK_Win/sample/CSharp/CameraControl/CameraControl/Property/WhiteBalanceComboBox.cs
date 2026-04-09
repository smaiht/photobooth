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
using System.Runtime.InteropServices;

namespace CameraControl
{
    class WhiteBalanceComboBox : PropertyComboBox, IObserver
    {

        private ActionSource _actionSource;

        private EDSDKLib.EDSDK.EdsPropertyDesc _desc;

        public void SetActionSource(ref ActionSource actionSource) { _actionSource = actionSource; }


        public WhiteBalanceComboBox()
        {
            map.Add(0, "Auto: Ambience priority");
            map.Add(1, "Daylight");
            map.Add(2, "Cloudy");
            map.Add(3, "Tungsten light");
            map.Add(4, "White fluorescent light");
            map.Add(5, "Flash");
            map.Add(6, "Custom1");
            map.Add(8, "Shade");
            map.Add(9, "Color temp.");
            map.Add(10, "Custom white balance: PC-1");
            map.Add(11, "Custom white balance: PC-2");
            map.Add(12, "Custom white balance: PC-3");
            map.Add(15, "Custom2");
            map.Add(16, "Custom3");
            map.Add(17, "Underwater");
            map.Add(18, "Custom4");
            map.Add(19, "Custom5");
            map.Add(20, "Custom white balance: PC-4");
            map.Add(21, "Custom white balance: PC-5");
            map.Add(23, "Auto: White priority");
            map.Add(24, "Color temp.2");
            map.Add(25, "Color temp.3");
            map.Add(26, "Color temp.4");
        }

        protected override void OnSelectionChangeCommitted(EventArgs e)
        {
            if (this.SelectedItem != null)
            {
                uint key = (uint)_desc.PropDesc[this.SelectedIndex];

                _actionSource.FireEvent(ActionEvent.Command.SET_WHITE_BALANCE, (IntPtr)key);
            }
        }

        public void Update(Observable from, CameraEvent e)
        {

            CameraModel model = (CameraModel)from;
            CameraEvent.Type eventType = CameraEvent.Type.NONE;

            if ((eventType = e.GetEventType()) == CameraEvent.Type.PROPERTY_CHANGED || eventType == CameraEvent.Type.PROPERTY_DESC_CHANGED)
            {
                uint propertyID = (uint)e.GetArg();

                if (propertyID == EDSDKLib.EDSDK.PropID_WhiteBalance)
                {
                    uint property = (uint)model.WhiteBalance;

                    //Update property
                    switch (eventType)
                    {
                        case CameraEvent.Type.PROPERTY_CHANGED:
                            this.UpdateProperty(property);
                            break;

                        case CameraEvent.Type.PROPERTY_DESC_CHANGED:
                            _desc = model.WhiteBalanceDesc;
                            this.UpdatePropertyDesc(ref _desc);
                            this.UpdateProperty(property);
                            break;
                    }
                }
                else if (propertyID == EDSDKLib.EDSDK.PropID_Evf_ClickWBCoeffs)
                {
                    //Update property
                    switch (eventType)
                    {
                        case CameraEvent.Type.PROPERTY_CHANGED:
                            int size;
                            EDSDKLib.EDSDK.EdsDataType datatype;
                            uint err = EDSDKLib.EDSDK.EdsGetPropertySize(model.Camera, EDSDKLib.EDSDK.PropID_Evf_ClickWBCoeffs, 0, out datatype, out size);
                            if (err != EDSDKLib.EDSDK.EDS_ERR_OK)
                            {
                                return;
                            }

                            //Get the WB coefficient
                            EDSDKLib.EDSDK.EdsManualWBData wbCoefs = new EDSDKLib.EDSDK.EdsManualWBData();
                            IntPtr ptr = Marshal.AllocHGlobal(size);
                            err = EDSDKLib.EDSDK.EdsGetPropertyData(model.Camera, EDSDKLib.EDSDK.PropID_Evf_ClickWBCoeffs, 0, size, ptr);
                            if (err != EDSDKLib.EDSDK.EDS_ERR_OK)
                            {
                                Marshal.FreeHGlobal(ptr);
                                return;
                            }

                            //Set the WB coefficient converted to the manual white balance data structure to manual white balance.
                            wbCoefs = EDSDKLib.EDSDK.MarshalPtrToManualWBData(ptr);
                            byte[] mwb = EDSDKLib.EDSDK.ConvertMWB(wbCoefs);
                            err = EDSDKLib.EDSDK.EdsSetPropertyData(model.Camera, EDSDKLib.EDSDK.PropID_ManualWhiteBalanceData, 0, mwb.Length, mwb);
                            if (err != EDSDKLib.EDSDK.EDS_ERR_OK)
                            {
                                Marshal.FreeHGlobal(ptr);
                                return;
                            }

                            //Change the camera's white balance setting to manual white balance.
                            err = EDSDKLib.EDSDK.EdsSetPropertyData(model.Camera, EDSDKLib.EDSDK.PropID_WhiteBalance, 0, sizeof(uint), 6);

                            Marshal.FreeHGlobal(ptr);
                            break;
                    }
                }
            }
        }
    }
}
