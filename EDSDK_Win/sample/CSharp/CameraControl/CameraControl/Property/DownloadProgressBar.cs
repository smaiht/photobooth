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
    class DownloadProgressBar : ProgressBar, IObserver
    {
        public void Update(Observable from, CameraEvent e)
        {
            CameraModel model = (CameraModel)from;
            CameraEvent.Type eventType = CameraEvent.Type.NONE;

            if ((eventType = e.GetEventType()) == CameraEvent.Type.PROGRESS)
            {
                uint percentage = (uint)e.GetArg();
                this.UpdateProperty(percentage);
            }
            if ((eventType = e.GetEventType()) == CameraEvent.Type.DOWNLOAD_COMPLETE)
            {
                System.Threading.Thread.Sleep(1000);
                uint percentage = (uint)0;
                this.UpdateProperty(percentage);
            }
        }
    }
}
