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
    class AeModeComboBox : PropertyComboBox, IObserver
    {
        private ActionSource _actionSource;

        private EDSDKLib.EDSDK.EdsPropertyDesc _desc;

        public void SetActionSource(ref ActionSource actionSource) { _actionSource = actionSource; }

        public AeModeComboBox()
        {
            map.Add(0, "P");
            map.Add(1, "Tv");
            map.Add(2, "Av");
            map.Add(3, "M");
            map.Add(55, "Fv");
            map.Add(4, "Bulb");
            map.Add(5, "A-DEP");
            map.Add(6, "DEP");
            map.Add(7, "C1");
            map.Add(8, "Lock");
            map.Add(9, "GreenMode");
            map.Add(10, "Night Portrait");
            map.Add(11, "Sports");
            map.Add(12, "Portrait");
            map.Add(13, "Landscape");
            map.Add(14, "Close-up");
            map.Add(15, "No Strobo");
            map.Add(16, "C2");
            map.Add(17, "C3");
            map.Add(19, "Creative Auto");
            map.Add(20, "Movies");
            map.Add(21, "Photo In Movie");
            map.Add(22, "Scene Intelligent Auto");
            map.Add(23, "Handheld Night Scene");
            map.Add(24, "HDR Backlight Control");
            map.Add(25, "SCN");
            map.Add(26, "Kids");
            map.Add(27, "Food");
            map.Add(28, "Candlelight");
            map.Add(29, "Creative filters");
            map.Add(30, "Grainy B/W");
            map.Add(31, "Soft focus");
            map.Add(32, "Toy camera effect");
            map.Add(33, "Fish-eye effect");
            map.Add(34, "Water painting effect");
            map.Add(35, "Miniature effect");
            map.Add(36, "HDR art standard");
            map.Add(37, "HDR art vivid");
            map.Add(38, "HDR art bold");
            map.Add(39, "HDR art embossed");
            map.Add(40, "Dream");
            map.Add(41, "Old Movies");
            map.Add(42, "Memory");
            map.Add(43, "Dramatic B&W");
            map.Add(44, "Miniature effect movie");
            map.Add(45, "Panning");
            map.Add(46, "Group Photo");
            map.Add(49, "HDR Movie");
            map.Add(50, "Self Portrait");
            map.Add(51, "Plus Movie Auto"); 
            map.Add(52, "Smooth skin");
            map.Add(53, "Panorama");
            map.Add(54, "Silent Mode");
            map.Add(56, "Art bold effect");
            map.Add(57, "Fireworks");
            map.Add(58, "Star portrait");
            map.Add(59, "Star nightscape");
            map.Add(60, "Star trails");
            map.Add(61, "Star time-lapse movie");
            map.Add(62, "Background blur");

            map.Add(0xffffffff, "unknown");
        }

        protected override void OnSelectionChangeCommitted(EventArgs e)
        {
            if (this.SelectedItem != null)
            {
                uint key = (uint)_desc.PropDesc[this.SelectedIndex];

                _actionSource.FireEvent(ActionEvent.Command.SET_AE_MODE, (IntPtr)key);
            }
        }

        public void Update(Observable from, CameraEvent e)
        {

            CameraModel model = (CameraModel)from;
            CameraEvent.Type eventType = CameraEvent.Type.NONE;

            if ((eventType = e.GetEventType()) == CameraEvent.Type.PROPERTY_CHANGED || eventType == CameraEvent.Type.PROPERTY_DESC_CHANGED)
            {
                uint propertyID = (uint)e.GetArg();

                if (propertyID == EDSDKLib.EDSDK.PropID_AEModeSelect)
                {
                    uint property = model.AEMode;
                    //Update property
                    switch (eventType)
                    {
                        case CameraEvent.Type.PROPERTY_CHANGED:
                            this.UpdateProperty(property);
                            break;

                        case CameraEvent.Type.PROPERTY_DESC_CHANGED:
                            _desc = model.AEModeDesc;
                            this.UpdatePropertyDesc(ref _desc);
                            this.UpdateProperty(property);
                            break;

                    }
                }
            }
        }
    }
}
