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
    class BatteryLebelLabel : InfoLabel, IObserver
    {

        public void Update(Observable from, CameraEvent e)
        {
            CameraEvent.Type eventType = CameraEvent.Type.NONE;

            if ((eventType = e.GetEventType()) == CameraEvent.Type.PROPERTY_CHANGED)
            {
                uint propertyID = (uint)e.GetArg();

                if (propertyID == EDSDKLib.EDSDK.PropID_BatteryLevel)
                {

                    //Update property
                    switch (eventType)
                    {
                        case CameraEvent.Type.PROPERTY_CHANGED:

                            CameraModel model = (CameraModel)from;
                            string infoText = "AC power";
                            if (0xffffffff != model.BatteryLebel)
                            {
                                infoText = model.BatteryLebel.ToString() + "%";
                            }
                            this.UpdateProperty(infoText);
                            break;
                    }
                }
            }
        }
    }
}
