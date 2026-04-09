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
using System.Runtime.InteropServices;
using System.Windows.Forms;

namespace CameraControl
{
    public partial class MainWindow : Form, IObserver
    {
        private CameraController _controller = null;
        private ActionSource _actionSource = new ActionSource();
        private List<ActionListener> _actionListenerList = new List<ActionListener>();
        private IObserver formAs = null;
        private Form _remoteCapture = null;
        private IntPtr[] _volumes = new IntPtr[2];
        private int _volume_count = 0;

        public MainWindow(ref CameraController controller)
        {
            uint err = EDSDKLib.EDSDK.EDS_ERR_OK;
            // Get initial volume
            EDSDKLib.EDSDK.EdsVolumeInfo outVolumeInfo;

            formAs = this;
            InitializeComponent();

            _controller = controller;
            err = EDSDKLib.EDSDK.EdsGetChildCount(_controller.GetModel().Camera, out _volume_count);
            if (_volume_count > 0){
                 err = EDSDKLib.EDSDK.EdsGetChildAtIndex(_controller.GetModel().Camera, 0, out _volumes[0]);
                 err = EDSDKLib.EDSDK.EdsGetVolumeInfo(_volumes[0], out outVolumeInfo);
                 if (outVolumeInfo.StorageType != (uint)EDSDKLib.EDSDK.EdsStorageType.Non)
                 {
                     this.button2.Enabled = true;
                     this.button2.Text = "Memory Card 1 (" + outVolumeInfo.szVolumeLabel + ")";
                     this.button7.Enabled = true;
                     this.button7.Text = "Memory Card 1 (" + outVolumeInfo.szVolumeLabel + ")";
                 }
                 if (_volume_count > 1)
                 {
                     err = EDSDKLib.EDSDK.EdsGetChildAtIndex(_controller.GetModel().Camera, 1, out _volumes[1]);
                     err = EDSDKLib.EDSDK.EdsGetVolumeInfo(_volumes[1], out outVolumeInfo);
                     if (outVolumeInfo.StorageType != (uint)EDSDKLib.EDSDK.EdsStorageType.Non)
                     {
                         this.button5.Enabled = true;
                         this.button5.Text = "Memory Card 2 (" + outVolumeInfo.szVolumeLabel + ")";
                         this.button8.Enabled = true;
                         this.button8.Text = "Memory Card 2 (" + outVolumeInfo.szVolumeLabel + ")";
                     }
                 }
            }



            _actionListenerList.Add((ActionListener)_controller);

            _actionListenerList.ForEach(actionListener => _actionSource.AddActionListener(ref actionListener));


        }

        private void button1_Click(object sender, EventArgs e)
        {
            _remoteCapture = new RemoteCapture(ref _controller, ref _actionSource);
            _remoteCapture.ShowDialog(this);
            _remoteCapture.Dispose();
        }

        private void button2_Click(object sender, EventArgs e)
        {
            IObserver frmProgress = new Progress(ref _controller);
            _controller.GetModel().Add(ref frmProgress);

            _controller.DownloadFile(_volumes[0]);

            ((Progress)frmProgress).ShowDialog();

            _controller.GetModel().Remove(ref frmProgress);
        }

        private void button3_Click(object sender, EventArgs e)
        {
            IObserver frmSetting = new CameraSetting(ref _controller, ref _volumes, ref _volume_count);

            // UIlock
            EDSDKLib.EDSDK.EdsSendStatusCommand(_controller.GetModel().Camera, EDSDKLib.EDSDK.CameraState_UILock, 1);
            _controller.GetModel().Add(ref frmSetting);

            ((CameraSetting)frmSetting).ShowSettingDialog();

            _controller.GetModel().Remove(ref frmSetting);

            // UIUnlock
            EDSDKLib.EDSDK.EdsSendStatusCommand(_controller.GetModel().Camera, EDSDKLib.EDSDK.CameraState_UIUnLock, 1);
        }

        public void Update(Observable from, CameraEvent e)
        {
            CameraEvent.Type eventType = e.GetEventType();

            switch (eventType)
            {
                case CameraEvent.Type.SHUT_DOWN:

                    MessageBox.Show("Camera is disconnected");

                    if (_remoteCapture != null && !_remoteCapture.IsDisposed)
                    {
                        _remoteCapture.Close();
                        _remoteCapture.Dispose();
                    }

                    this.Close();

                    break;

                case CameraEvent.Type.PROPERTY_CHANGED:
                    if (null != _remoteCapture)
                    {
                        uint propertyID = (uint)e.GetArg();
                        if (propertyID == EDSDKLib.EDSDK.PropID_Evf_AFMode)
                        {
                            (_remoteCapture as RemoteCapture).controlFocusButton((int)EDSDKLib.EDSDK.EdsEvfAFMode.Evf_AFMode_LiveFace != _controller.GetModel().EvfAFMode);
                        }
                        if (propertyID == EDSDKLib.EDSDK.PropID_FixedMovie)
                        {
                            (_remoteCapture as RemoteCapture).updateFixedMovie(_controller.GetModel().FixedMovie);
                        }
                        if (propertyID == EDSDKLib.EDSDK.PropID_MirrorLockUpState)
                        {
                            (_remoteCapture as RemoteCapture).updateMirrorLockUpState(_controller.GetModel().MirrorLockUpState);
                        }
                    }
                    break;

                case CameraEvent.Type.ANGLEINFO:
                    if (null != _remoteCapture)
                    {
                        IntPtr cameraPosPtr = e.GetArg();
                        if (cameraPosPtr != IntPtr.Zero)
                        {
                            EDSDKLib.EDSDK.EdsCameraPos cameraPos = (EDSDKLib.EDSDK.EdsCameraPos)Marshal.PtrToStructure(cameraPosPtr, typeof(EDSDKLib.EDSDK.EdsCameraPos));
                            double pos = cameraPos.position;
                            // Convert to floating point
                            double roll = cameraPos.rolling * 0.01;
                            double pitc = cameraPos.pitching * 0.01;
                            (_remoteCapture as RemoteCapture).updateAngleInfoLabel(pos.ToString(), roll.ToString(), pitc.ToString());
                        }
                        else
                        {
                            uint err = EDSDKLib.EDSDK.EdsSendCommand(_controller.GetModel().Camera, EDSDKLib.EDSDK.CameraCommand_RequestRollPitchLevel, 1);
                            (_remoteCapture as RemoteCapture).updateAngleInfoLabel("-", "-", "-");
                        }
                    }
                    break;

                case CameraEvent.Type.MOUSE_CURSOR:
                    if (null != _remoteCapture)
                    {
                        IntPtr onOffPtr = e.GetArg();
                        if (onOffPtr != IntPtr.Zero)
                        {
                            (_remoteCapture as RemoteCapture).changeMouseCursor(true);
                        }
                        else
                        {
                            (_remoteCapture as RemoteCapture).changeMouseCursor(false);
                            if(_controller.ClickType == 1)
                            {
                                _actionSource.FireEvent(ActionEvent.Command.CLICK_MOUSE_WB, IntPtr.Zero);
                            }
                            if(_controller.ClickType == 2)
                            {
                                _actionSource.FireEvent(ActionEvent.Command.CLICK_MOUSE_AF, IntPtr.Zero);
                            }
                        }
                    }
                    break;

                default:
                    break;
            }
        }

        private void MainWindow_FormClosing(object sender, FormClosingEventArgs e)
        {
            _actionSource.FireEvent(ActionEvent.Command.CLOSING, IntPtr.Zero);

            _actionListenerList.ForEach(actionListener => _actionSource.RemoveActionListener(ref actionListener));
        }

        private void button5_Click(object sender, EventArgs e)
        {
            IObserver frmProgress = new Progress(ref _controller);
            _controller.GetModel().Add(ref frmProgress);

            _controller.DownloadFile(_volumes[1]);

            ((Progress)frmProgress).ShowDialog();

            _controller.GetModel().Remove(ref frmProgress);
        }

        private void button7_Click(object sender, EventArgs e)
        {
            IObserver frmProgress = new Progress(ref _controller);
            _controller.GetModel().Add(ref frmProgress);

            _controller.DeleteFile(_volumes[0]);

            ((Progress)frmProgress).ShowDialog();

            _controller.GetModel().Remove(ref frmProgress);
        }

        private void button8_Click(object sender, EventArgs e)
        {
            IObserver frmProgress = new Progress(ref _controller);
            _controller.GetModel().Add(ref frmProgress);

            _controller.DeleteFile(_volumes[1]);

            ((Progress)frmProgress).ShowDialog();

            _controller.GetModel().Remove(ref frmProgress);
        }

        private void groupBox1_Enter(object sender, EventArgs e)
        {

        }

        private void MainWindow_Load(object sender, EventArgs e)
        {

        }
    }
}
