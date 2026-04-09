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
    class EvfAfModeComboBox : PropertyComboBox, IObserver
    {
        private ActionSource _actionSource;

        private EDSDKLib.EDSDK.EdsPropertyDesc _desc;

        public void SetActionSource(ref ActionSource actionSource) { _actionSource = actionSource; }


        public EvfAfModeComboBox()
        {
            map.Add(0x00, "Quick mode");
            map.Add(0x01, "1-point AF");
            map.Add(0x02, "Face+Tracking");
            map.Add(0x03, "FlexiZone - Multi");
            map.Add(0x04, "Zone AF");
            map.Add(0x05, "Expand AF area");
            map.Add(0x06, "Expand AF area: Around");
            map.Add(0x07, "Large Zone AF: Horizontal");
            map.Add(0x08, "Large Zone AF: Vertical");
            map.Add(0x09, "Catch AF");
            map.Add(0x0a, "Spot AF");
            map.Add(0x0b, "Flexible Zone AF 1");
            map.Add(0x0c, "Flexible Zone AF 2");
            map.Add(0x0d, "Flexible Zone AF 3");
            map.Add(0x0e, "Whole area AF");
            map.Add(0x0f, "No Traking Spot AF");
            map.Add(0x10, "No Traking 1-point AF");
            map.Add(0x11, "No Traking Expand AF area");
            map.Add(0x12, "No Traking Expand AF area: Around");
            map.Add(0xffffffff, "unknown");
        }

        protected override void OnSelectionChangeCommitted(EventArgs e)
        {
            if (this.SelectedItem != null)
            {
                uint key = (uint)_desc.PropDesc[this.SelectedIndex];

                _actionSource.FireEvent(ActionEvent.Command.SET_EVF_AFMODE, (IntPtr)key);
            }
        }

        public void Update(Observable from, CameraEvent e)
        {
            CameraModel model = (CameraModel)from;
            CameraEvent.Type eventType = CameraEvent.Type.NONE;

            if ((eventType = e.GetEventType()) == CameraEvent.Type.PROPERTY_CHANGED || eventType == CameraEvent.Type.PROPERTY_DESC_CHANGED)
            {
                uint propertyID = (uint)e.GetArg();

                if (propertyID == EDSDKLib.EDSDK.PropID_Evf_AFMode)
                {
                    uint property = model.EvfAFMode;

                    //Update property
                    switch (eventType)
                    {
                        case CameraEvent.Type.PROPERTY_CHANGED:
                            // At the time of application start, if the camera setting is 'Catch AF', make 'Evf_AFMode_LiveFace' forcibly.
                            if (0x09 == property)
                            {
                                EDSDKLib.EDSDK.EdsSetPropertyData(model.Camera, EDSDKLib.EDSDK.PropID_Evf_AFMode, 0, sizeof(uint), 0x02);
                            }
                            else
                            {
                                this.UpdateProperty(property);
                            }
                            break;

                        case CameraEvent.Type.PROPERTY_DESC_CHANGED:
                            // If property is 'Catch AF', do not call UpdateProperty().
                            _desc = model.EvfAFModeDesc;
                            this.UpdatePropertyDesc(ref _desc);
                            if (0x09 != property)
                            {
                                this.UpdateProperty(property);
                            }
                            break;
                    }
                }
            }
        }
    }
}
