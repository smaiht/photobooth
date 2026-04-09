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
    class DriveModeComboBox : PropertyComboBox, IObserver
    {
        private ActionSource _actionSource;

        private EDSDKLib.EDSDK.EdsPropertyDesc _desc;

        public void SetActionSource(ref ActionSource actionSource) { _actionSource = actionSource; }

        public DriveModeComboBox()
        {
            map.Add(0x00, "Single shooting");
            map.Add(0x01, "Medium speed continuous");
            map.Add(0x04, "High speed continuous");
            map.Add(0x05, "Low speed continuous");
            map.Add(0x06, "Single Silent(Soft) shooting");
            map.Add(0x07, "Self-timer:Continuous");
            map.Add(0x10, "Self-timer:10 sec");
            map.Add(0x11, "Self-timer:2 sec");
            map.Add(0x12, "High speed continuous +");
            map.Add(0x13, "Silent single shooting");
            map.Add(0x14, "Silent(Soft) contin shooting");
            map.Add(0x15, "Silent HS continuous");
            map.Add(0x16, "Silent(Soft) LS continuous");
        }

        protected override void OnSelectionChangeCommitted(EventArgs e)
        {
            if (this.SelectedItem != null)
            {
                uint key = (uint)_desc.PropDesc[this.SelectedIndex];

                _actionSource.FireEvent(ActionEvent.Command.SET_DRIVE_MODE, (IntPtr)key);
            }
        }

        public void Update(Observable from, CameraEvent e)
        {
            CameraModel model = (CameraModel)from;
            CameraEvent.Type eventType = CameraEvent.Type.NONE;
            
            if ((eventType = e.GetEventType()) == CameraEvent.Type.PROPERTY_CHANGED || eventType == CameraEvent.Type.PROPERTY_DESC_CHANGED)
            {
                uint propertyID = (uint)e.GetArg();

                if (propertyID == EDSDKLib.EDSDK.PropID_DriveMode)
                {
                    uint property = model.DriveMode;

                    //Update property
                    switch (eventType)
                    {
                        case CameraEvent.Type.PROPERTY_CHANGED:
                            this.UpdateProperty(property);
                            break;

                        case CameraEvent.Type.PROPERTY_DESC_CHANGED:
                            _desc = model.DriveModeDesc;
                            this.UpdatePropertyDesc(ref _desc);
                            this.UpdateProperty(property);
                            break;
                    }
                }
            }
        }
    }
}
