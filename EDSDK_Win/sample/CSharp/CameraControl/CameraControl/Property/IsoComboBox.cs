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
    class IsoComboBox : PropertyComboBox, IObserver
    {
        private ActionSource _actionSource;

        private EDSDKLib.EDSDK.EdsPropertyDesc _desc;

        public void SetActionSource(ref ActionSource actionSource) { _actionSource = actionSource; }


        public IsoComboBox()
        {
            map.Add(0x00, "Auto");
            map.Add(0x28, "6");
            map.Add(0x30, "12");
            map.Add(0x38, "25");
            map.Add(0x40, "50");
            map.Add(0x48, "100");
            map.Add(0x4b, "125");
            map.Add(0x4d, "160");
            map.Add(0x50, "200");
            map.Add(0x53, "250");
            map.Add(0x55, "320");
            map.Add(0x58, "400");
            map.Add(0x5b, "500");
            map.Add(0x5d, "640");
            map.Add(0x60, "800");
            map.Add(0x63, "1000");
            map.Add(0x65, "1250");
            map.Add(0x68, "1600");
            map.Add(0x6b, "2000");
            map.Add(0x6d, "2500");
            map.Add(0x70, "3200");
            map.Add(0x73, "4000");
            map.Add(0x75, "5000");
            map.Add(0x78, "6400");
            map.Add(0x7b, "8000");
            map.Add(0x7d, "10000");
            map.Add(0x80, "12800");
            map.Add(0x83, "16000");
            map.Add(0x85, "20000");
            map.Add(0x88, "25600");
            map.Add(0x8b, "32000");
            map.Add(0x8d, "40000");
            map.Add(0x90, "51200");
            map.Add(0x93, "64000");
            map.Add(0x95, "80000");
            map.Add(0x98, "102400");
            map.Add(0xa0, "204800");
            map.Add(0xa8, "409600");
            map.Add(0xb0, "819200");
            map.Add(0xffffffff, "unknown");

        }

        protected override void OnSelectionChangeCommitted(EventArgs e)
        {
            if (this.SelectedItem != null)
            {
                uint key = (uint)_desc.PropDesc[this.SelectedIndex];
                _actionSource.FireEvent(ActionEvent.Command.SET_ISO_SPEED, (IntPtr)key);
            }
        }

        public void Update(Observable from, CameraEvent e)
        {
            CameraModel model = (CameraModel)from;
            CameraEvent.Type eventType = CameraEvent.Type.NONE;

            if ((eventType = e.GetEventType()) == CameraEvent.Type.PROPERTY_CHANGED || eventType == CameraEvent.Type.PROPERTY_DESC_CHANGED)
            {
                uint propertyID = (uint)e.GetArg();

                if (propertyID == EDSDKLib.EDSDK.PropID_ISOSpeed)
                {
                    uint property = model.Iso;
                    //Update property
                    switch (eventType)
                    {
                        case CameraEvent.Type.PROPERTY_CHANGED:
                            this.UpdateProperty(property);
                            break;

                        case CameraEvent.Type.PROPERTY_DESC_CHANGED:
                            _desc = model.IsoDesc;
                            this.UpdatePropertyDesc(ref _desc);
                            this.UpdateProperty(property);
                            break;
                    }
                }
            }
        }
    }
}
