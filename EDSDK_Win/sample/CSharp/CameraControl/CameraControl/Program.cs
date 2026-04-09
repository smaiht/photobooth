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
using System.Windows.Forms;
using System.Runtime.InteropServices;

namespace CameraControl
{
    static class Program
    {
        /// <summary>
        /// </summary>
        [STAThread]
        static void Main()
        {
            // Initialization of SDK
            uint err = EDSDKLib.EDSDK.EdsInitializeSDK();

            bool isSDKLoaded = false;
            if (err == EDSDKLib.EDSDK.EDS_ERR_OK)
            {
                isSDKLoaded = true;
            }

            //Acquisition of camera list
            IntPtr cameraList = IntPtr.Zero;
            if (err == EDSDKLib.EDSDK.EDS_ERR_OK)
            {
                err = EDSDKLib.EDSDK.EdsGetCameraList(out cameraList);
            }

            //Acquisition of number of Cameras
            if (err == EDSDKLib.EDSDK.EDS_ERR_OK)
            {
                int count = 0;
                err = EDSDKLib.EDSDK.EdsGetChildCount(cameraList, out count);
                if (count == 0)
                {
                    err = EDSDKLib.EDSDK.EDS_ERR_DEVICE_NOT_FOUND;
                }
            }


            //Acquisition of camera at the head of the list
            IntPtr camera = IntPtr.Zero;
            if (err == EDSDKLib.EDSDK.EDS_ERR_OK)
            {
                err = EDSDKLib.EDSDK.EdsGetChildAtIndex(cameraList, 0, out camera);
            }

            //Acquisition of camera information
            EDSDKLib.EDSDK.EdsDeviceInfo deviceInfo;
            if (err == EDSDKLib.EDSDK.EDS_ERR_OK)
            {
                err = EDSDKLib.EDSDK.EdsGetDeviceInfo(camera, out deviceInfo);
                if (err == EDSDKLib.EDSDK.EDS_ERR_OK && camera == IntPtr.Zero)
                {
                    err = EDSDKLib.EDSDK.EDS_ERR_DEVICE_NOT_FOUND;
                }
            }


            //Release camera list
            if (cameraList != IntPtr.Zero)
            {
                EDSDKLib.EDSDK.EdsRelease(cameraList);
            }

            //Create Camera model
            CameraModel model = null;
            if (err == EDSDKLib.EDSDK.EDS_ERR_OK)
            {
                model = new CameraModel(camera);
            }

            if (err != EDSDKLib.EDSDK.EDS_ERR_OK)
            {
                MessageBox.Show("Cannot detect camera");
            }
            
            EDSDKLib.EDSDK.EdsPropertyEventHandler handlePropertyEvent = new EDSDKLib.EDSDK.EdsPropertyEventHandler(CameraEventListener.HandlePropertyEvent);
            EDSDKLib.EDSDK.EdsObjectEventHandler handleObjectEvent = new EDSDKLib.EDSDK.EdsObjectEventHandler(CameraEventListener.HandleObjectEvent);
            EDSDKLib.EDSDK.EdsStateEventHandler handleStateEvent = new EDSDKLib.EDSDK.EdsStateEventHandler(CameraEventListener.HandleStateEvent);
           
            CameraController controller;
            if (err == EDSDKLib.EDSDK.EDS_ERR_OK)
            {
                //Create CameraController
                controller = new CameraController(ref model);
                GCHandle handle = GCHandle.Alloc(controller);
                IntPtr ptr = GCHandle.ToIntPtr(handle);

                //Set Property Event Handler
                if (err == EDSDKLib.EDSDK.EDS_ERR_OK)
                {
                    err = EDSDKLib.EDSDK.EdsSetPropertyEventHandler(camera, EDSDKLib.EDSDK.PropertyEvent_All, handlePropertyEvent, ptr);
                }

                //Set Object Event Handler
                if (err == EDSDKLib.EDSDK.EDS_ERR_OK)
                {
                    err = EDSDKLib.EDSDK.EdsSetObjectEventHandler(camera, EDSDKLib.EDSDK.ObjectEvent_All, handleObjectEvent, ptr);
                }

                //Set State Event Handler
                if (err == EDSDKLib.EDSDK.EDS_ERR_OK)
                {
                    err = EDSDKLib.EDSDK.EdsSetCameraStateEventHandler(camera, EDSDKLib.EDSDK.StateEvent_All, handleStateEvent, ptr);
                }

                controller.Run();

                Application.EnableVisualStyles();
                Application.SetCompatibleTextRenderingDefault(false);

                IObserver form = new MainWindow(ref controller);
                model.Add(ref form);
                Application.Run((MainWindow)form);

                handle.Free();
            }

            GC.KeepAlive(handlePropertyEvent);
            GC.KeepAlive(handleObjectEvent);
            GC.KeepAlive(handleStateEvent);

            //Release Camera
            if (camera != IntPtr.Zero)
            {
                EDSDKLib.EDSDK.EdsRelease(camera);
            }

            //Termination of SDK
            if (isSDKLoaded)
            {
                EDSDKLib.EDSDK.EdsTerminateSDK();
            }
        }
    }
}
