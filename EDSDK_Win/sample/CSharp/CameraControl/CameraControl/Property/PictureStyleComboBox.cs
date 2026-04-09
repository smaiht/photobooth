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
    class PictureStyleComboBox : PropertyComboBox, IObserver
    {
        private ActionSource _actionSource;

        private EDSDKLib.EDSDK.EdsPropertyDesc _desc;

        public void SetActionSource(ref ActionSource actionSource) { _actionSource = actionSource; }

        public PictureStyleComboBox()
        {
            map.Add(0x0081, "Standard");
            map.Add(0x0082, "Portrait");
            map.Add(0x0083, "Landsscape");
            map.Add(0x0084, "Neutral");
            map.Add(0x0085, "Faithful");
            map.Add(0x0086, "Monochrome");
            map.Add(0x0087, "Auto");
            map.Add(0x0088, "FineDetail");
            map.Add(0X0021, "User Def. 1");
            map.Add(0X0022, "User Def. 2");
            map.Add(0X0023, "User Def. 3");
            map.Add(0x0041, "PC1");
            map.Add(0x0042, "PC2");
            map.Add(0x0043, "PC3");
            
        }

        protected override void OnSelectionChangeCommitted(EventArgs e)
        {
            if (this.SelectedItem != null)
            {
                uint key = (uint)_desc.PropDesc[this.SelectedIndex];

                _actionSource.FireEvent(ActionEvent.Command.SET_PICTURESTYLE, (IntPtr)key);
            }
        }


        public void Update(Observable from, CameraEvent e)
        {

            CameraModel model = (CameraModel)from;
            CameraEvent.Type eventType = CameraEvent.Type.NONE;

            if ((eventType = e.GetEventType()) == CameraEvent.Type.PROPERTY_CHANGED || eventType == CameraEvent.Type.PROPERTY_DESC_CHANGED)
            {
                uint propertyID = (uint)e.GetArg();

                if (propertyID == EDSDKLib.EDSDK.PropID_PictureStyle)
                {
                    uint property = model.PictureStyle;

                    //Update property
                    switch (eventType)
                    {
                        case CameraEvent.Type.PROPERTY_CHANGED:
                            this.UpdateProperty(property);
                            break;

                        case CameraEvent.Type.PROPERTY_DESC_CHANGED:
                            _desc = model.PictureStyleDesc;
                            this.UpdatePropertyDesc(ref _desc);
                            this.UpdateProperty(property);
                            break;
                    }
                }
            }
        }
    }
}
