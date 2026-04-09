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
    class TvComboBox : PropertyComboBox, IObserver
    {
        private ActionSource _actionSource;

        private EDSDKLib.EDSDK.EdsPropertyDesc _desc;

        public void SetActionSource(ref ActionSource actionSource) { _actionSource = actionSource; }


        public TvComboBox()
        {
            map.Add(0x04, "Auto");
            map.Add(0x0c, "Bulb");
            map.Add(0x10, "30''");
            map.Add(0x13, "25''");
            map.Add(0x14, "20''");
            map.Add(0x15, "20''");
            map.Add(0x18, "15''");
            map.Add(0x1B, "13''");
            map.Add(0x1C, "10''");
            map.Add(0x1D, "10''");
            map.Add(0x20, "8''");
            map.Add(0x23, "6''");
            map.Add(0x24, "6''");
            map.Add(0x25, "5''");
            map.Add(0x28, "4''");
            map.Add(0x2B, "3''2");
            map.Add(0x2C, "3''");
            map.Add(0x2D, "2''5");
            map.Add(0x30, "2''");
            map.Add(0x33, "1''6");
            map.Add(0x34, "1''5");
            map.Add(0x35, "1''3");
            map.Add(0x38, "1''");
            map.Add(0x3B, "0''8");
            map.Add(0x3C, "0''7");
            map.Add(0x3D, "0''6");
            map.Add(0x40, "0''5");
            map.Add(0x43, "0''4");
            map.Add(0x44, "0''3");
            map.Add(0x45, "0''3");
            map.Add(0x48, "4");
            map.Add(0x4B, "5");
            map.Add(0x4C, "6");
            map.Add(0x4D, "6");
            map.Add(0x50, "8");
            map.Add(0x53, "10");
            map.Add(0x54, "10");
            map.Add(0x55, "13");
            map.Add(0x58, "15");
            map.Add(0x5B, "20");
            map.Add(0x5C, "20");
            map.Add(0x5D, "25");
            map.Add(0x60, "30");
            map.Add(0x63, "40");
            map.Add(0x64, "45");
            map.Add(0x65, "50");
            map.Add(0x68, "60");
            map.Add(0x6B, "80");
            map.Add(0x6C, "90");
            map.Add(0x6D, "100");
            map.Add(0x70, "125");
            map.Add(0x73, "160");
            map.Add(0x74, "180");
            map.Add(0x75, "200");
            map.Add(0x78, "250");
            map.Add(0x7B, "320");
            map.Add(0x7C, "350");
            map.Add(0x7D, "400");
            map.Add(0x80, "500");
            map.Add(0x83, "640");
            map.Add(0x84, "750");
            map.Add(0x85, "800");
            map.Add(0x88, "1000");
            map.Add(0x8B, "1250");
            map.Add(0x8C, "1500");
            map.Add(0x8D, "1600");
            map.Add(0x90, "2000");
            map.Add(0x93, "2500");
            map.Add(0x94, "3000");
            map.Add(0x95, "3200");
            map.Add(0x98, "4000");
            map.Add(0x9B, "5000");
            map.Add(0x9C, "6000");
            map.Add(0x9D, "6400");
            map.Add(0xA0, "8000");
            map.Add(0xA3, "10000");
            map.Add(0xA4, "12000");
            map.Add(0xA5, "12800");
            map.Add(0xA8, "16000");
            map.Add(0xAB, "20000");
            map.Add(0xAC, "24000");
            map.Add(0xAD, "25600");
            map.Add(0xB0, "32000");
            map.Add(0xB3, "40000");
            map.Add(0xB4, "48000");
            map.Add(0xB5, "51200");
            map.Add(0xB8, "64000");
            map.Add(0xffffffff, "unknown");
        }

        protected override void OnSelectionChangeCommitted(EventArgs e)
        {
            if (this.SelectedItem != null)
            {
                uint key = (uint)_desc.PropDesc[this.SelectedIndex];

                _actionSource.FireEvent(ActionEvent.Command.SET_TV, (IntPtr)key);
            }
        }

        public void Update(Observable from, CameraEvent e)
        {
            CameraModel model = (CameraModel)from;
            CameraEvent.Type eventType = CameraEvent.Type.NONE;

            if ((eventType = e.GetEventType()) == CameraEvent.Type.PROPERTY_CHANGED || eventType == CameraEvent.Type.PROPERTY_DESC_CHANGED)
            {
                uint propertyID = (uint)e.GetArg();


                if (propertyID == EDSDKLib.EDSDK.PropID_Tv)
                {
                    uint property = model.Tv;

                    //Update property
                    switch (eventType)
                    {
                        case CameraEvent.Type.PROPERTY_CHANGED:
                            this.UpdateProperty(property);
                            break;

                        case CameraEvent.Type.PROPERTY_DESC_CHANGED:
                            _desc = model.TvDesc;
                            this.UpdatePropertyDesc(ref _desc);
                            this.UpdateProperty(property);
                            break;
                    }
                }
            }
        }
    }
}
