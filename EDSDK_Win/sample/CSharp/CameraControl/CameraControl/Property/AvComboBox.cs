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
    class AvComboBox : PropertyComboBox, IObserver
    {
        private ActionSource _actionSource;

        private EDSDKLib.EDSDK.EdsPropertyDesc _desc;

        public void SetActionSource(ref ActionSource actionSource) { _actionSource = actionSource; }


        public AvComboBox()
        {
            map.Add(0x00, "");
            map.Add(0x08, "1.0");
            map.Add(0x0B, "1.1");
            map.Add(0x0C, "1.2");
            map.Add(0x0D, "1.2");
            map.Add(0x10, "1.4");
            map.Add(0x13, "1.6");
            map.Add(0x14, "1.8");
            map.Add(0x15, "1.8");
            map.Add(0x18, "2.0");
            map.Add(0x1B, "2.2");
            map.Add(0x1C, "2.5");
            map.Add(0x1D, "2.5");
            map.Add(0x20, "2.8");
            map.Add(0x23, "3.2");
            map.Add(0x80, "3.3");
            map.Add(0x85, "3.4");
            map.Add(0x24, "3.5");
            map.Add(0x25, "3.5");
            map.Add(0x28, "4.0");
            map.Add(0x2B, "4.5");
            map.Add(0x2C, "4.5");
            map.Add(0x2D, "5.0");
            map.Add(0x30, "5.6");
            map.Add(0x33, "6.3");
            map.Add(0x34, "6.7");
            map.Add(0x35, "7.1");
            map.Add(0x38, "8.0");
            map.Add(0x3B, "9.0");
            map.Add(0x3C, "9.5");
            map.Add(0x3D, "10");
            map.Add(0x40, "11");
            map.Add(0x43, "13");
            map.Add(0x44, "13");
            map.Add(0x45, "14");
            map.Add(0x48, "16");
            map.Add(0x4B, "18");
            map.Add(0x4C, "19");
            map.Add(0x4D, "20");
            map.Add(0x50, "22");
            map.Add(0x53, "25");
            map.Add(0x54, "27");
            map.Add(0x55, "29");
            map.Add(0x58, "32");
            map.Add(0x5B, "36");
            map.Add(0x5C, "38");
            map.Add(0x5D, "40");
            map.Add(0x60, "45");
            map.Add(0x63, "51");
            map.Add(0x64, "54");
            map.Add(0x65, "57");
            map.Add(0x68, "64");
            map.Add(0x6B, "72");
            map.Add(0x6C, "76");
            map.Add(0x6D, "80");
            map.Add(0x70, "91");
            map.Add(0xFF, "Auto");
            map.Add(0xffffffff, "unknown");
        }

        protected override void OnSelectionChangeCommitted(EventArgs e)
        {
            if (this.SelectedItem != null)
            {
                uint key = (uint)_desc.PropDesc[this.SelectedIndex];

                _actionSource.FireEvent(ActionEvent.Command.SET_AV, (IntPtr)key);
            }
        }

        public void Update(Observable from, CameraEvent e)
        {

            CameraModel model = (CameraModel)from;
            CameraEvent.Type eventType = CameraEvent.Type.NONE;

            if ((eventType = e.GetEventType()) == CameraEvent.Type.PROPERTY_CHANGED || eventType == CameraEvent.Type.PROPERTY_DESC_CHANGED)
            {
                uint propertyID = (uint)e.GetArg();

                if (propertyID == EDSDKLib.EDSDK.PropID_Av)
                {
                    uint property = model.Av;

                    //Update property
                    switch (eventType)
                    {
                        case CameraEvent.Type.PROPERTY_CHANGED:
                            this.UpdateProperty(property);
                            break;

                        case CameraEvent.Type.PROPERTY_DESC_CHANGED:
                            _desc = model.AvDesc;
                            this.UpdatePropertyDesc(ref _desc);
                            this.UpdateProperty(property);
                            break;
                    }
                }
            }
        }
    }
}
