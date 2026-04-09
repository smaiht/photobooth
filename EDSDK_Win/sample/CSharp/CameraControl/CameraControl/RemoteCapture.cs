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
using System.Windows.Forms;
using System.Drawing;

namespace CameraControl
{
    public partial class RemoteCapture : Form
    {

        private CameraController _controller = null;

        private ActionSource _actionSource = null;

        private List<IObserver> _observerList = new List<IObserver>();

        Rectangle _clip;

        public RemoteCapture(ref CameraController controller , ref ActionSource actionSource)
        {
            InitializeComponent();
            
            _controller = controller;

            _actionSource = actionSource;

            CameraEvent e;

            _observerList.Add((IObserver)aeMode1);
            _observerList.Add((IObserver)av1);
            _observerList.Add((IObserver)evfPictureBox1);
            _observerList.Add((IObserver)tv1);
            _observerList.Add((IObserver)iso1);
            _observerList.Add((IObserver)meteringMode1);
            _observerList.Add((IObserver)exposureComp1);
            _observerList.Add((IObserver)imageQuality1);
            _observerList.Add((IObserver)evfAFMode1);
            _observerList.Add((IObserver)driveMode1);
            _observerList.Add((IObserver)whiteBalance1);
            _observerList.Add((IObserver)availableShotLabel1);
            _observerList.Add((IObserver)batteryLebelLabel1);
            _observerList.Add((IObserver)zoom1);
            _observerList.Add((IObserver)afMode1);
            _observerList.Add((IObserver)flashMode1);
            _observerList.Add((IObserver)downloadProgressBar1);
            _observerList.Add((IObserver)tempStatusLabel1);
            _observerList.Add((IObserver)movieQuality1);
            _observerList.Add((IObserver)pictureStyle1);
            _observerList.Add((IObserver)aspect1);
            _observerList.Add((IObserver)movieHFR1);

            System.Threading.Thread.Sleep(1000);

            _observerList.ForEach(observer => _controller.GetModel().Add(ref observer));

            aeMode1.SetActionSource(ref _actionSource);
            e = new CameraEvent(CameraEvent.Type.PROPERTY_DESC_CHANGED, (IntPtr)EDSDKLib.EDSDK.PropID_AEModeSelect);
            _controller.GetModel().NotifyObservers(e);

            av1.SetActionSource(ref _actionSource);
            e = new CameraEvent(CameraEvent.Type.PROPERTY_DESC_CHANGED, (IntPtr)EDSDKLib.EDSDK.PropID_Av);
            _controller.GetModel().NotifyObservers(e);

            evfPictureBox1.SetActionSource(ref _actionSource);

            tv1.SetActionSource(ref _actionSource);
            e = new CameraEvent(CameraEvent.Type.PROPERTY_DESC_CHANGED, (IntPtr)EDSDKLib.EDSDK.PropID_Tv);
            _controller.GetModel().NotifyObservers(e);


            iso1.SetActionSource(ref _actionSource);
            e = new CameraEvent(CameraEvent.Type.PROPERTY_DESC_CHANGED, (IntPtr)EDSDKLib.EDSDK.PropID_ISOSpeed);
            _controller.GetModel().NotifyObservers(e);


            meteringMode1.SetActionSource(ref _actionSource);
            e = new CameraEvent(CameraEvent.Type.PROPERTY_DESC_CHANGED, (IntPtr)EDSDKLib.EDSDK.PropID_MeteringMode);
            _controller.GetModel().NotifyObservers(e);


            exposureComp1.SetActionSource(ref _actionSource);
            e = new CameraEvent(CameraEvent.Type.PROPERTY_DESC_CHANGED, (IntPtr)EDSDKLib.EDSDK.PropID_ExposureCompensation);
            _controller.GetModel().NotifyObservers(e);


            imageQuality1.SetActionSource(ref _actionSource);
            e = new CameraEvent(CameraEvent.Type.PROPERTY_DESC_CHANGED, (IntPtr)EDSDKLib.EDSDK.PropID_ImageQuality);
            _controller.GetModel().NotifyObservers(e);


            evfAFMode1.SetActionSource(ref _actionSource);
            e = new CameraEvent(CameraEvent.Type.PROPERTY_DESC_CHANGED, (IntPtr)EDSDKLib.EDSDK.PropID_Evf_AFMode);
            _controller.GetModel().NotifyObservers(e);


            driveMode1.SetActionSource(ref _actionSource);
            e = new CameraEvent(CameraEvent.Type.PROPERTY_DESC_CHANGED, (IntPtr)EDSDKLib.EDSDK.PropID_DriveMode);
            _controller.GetModel().NotifyObservers(e);


            whiteBalance1.SetActionSource(ref _actionSource);
            e = new CameraEvent(CameraEvent.Type.PROPERTY_DESC_CHANGED, (IntPtr)EDSDKLib.EDSDK.PropID_WhiteBalance);
            _controller.GetModel().NotifyObservers(e);

            e = new CameraEvent(CameraEvent.Type.PROPERTY_CHANGED, (IntPtr)EDSDKLib.EDSDK.PropID_AFMode);
            _controller.GetModel().NotifyObservers(e);

            flashMode1.SetActionSource(ref _actionSource);
            e = new CameraEvent(CameraEvent.Type.PROPERTY_DESC_CHANGED, (IntPtr)EDSDKLib.EDSDK.PropID_DC_Strobe);
            _controller.GetModel().NotifyObservers(e);

            movieQuality1.SetActionSource(ref _actionSource);
            e = new CameraEvent(CameraEvent.Type.PROPERTY_DESC_CHANGED, (IntPtr)EDSDKLib.EDSDK.PropID_MovieParam);
            _controller.GetModel().NotifyObservers(e);

            movieHFR1.SetActionSource(ref _actionSource);
            e = new CameraEvent(CameraEvent.Type.PROPERTY_DESC_CHANGED, (IntPtr)EDSDKLib.EDSDK.PropID_MovieHFRSetting);
            _controller.GetModel().NotifyObservers(e);

            pictureStyle1.SetActionSource(ref _actionSource);
            e = new CameraEvent(CameraEvent.Type.PROPERTY_DESC_CHANGED, (IntPtr)EDSDKLib.EDSDK.PropID_PictureStyle);
            _controller.GetModel().NotifyObservers(e);

            aspect1.SetActionSource(ref _actionSource);
            e = new CameraEvent(CameraEvent.Type.PROPERTY_DESC_CHANGED, (IntPtr)EDSDKLib.EDSDK.PropID_Aspect);
            _controller.GetModel().NotifyObservers(e);

            zoom1.SetActionSource(ref _actionSource);
            label16.Text = zoom1.Value.ToString();
            e = new CameraEvent(CameraEvent.Type.PROPERTY_DESC_CHANGED, (IntPtr)EDSDKLib.EDSDK.PropID_DC_Zoom);
            _controller.GetModel().NotifyObservers(e);

            actionButton1.SetActionSource(ref _actionSource);
            actionButton1.Command = ActionEvent.Command.TAKE_PICTURE;

            actionButton3.SetActionSource(ref _actionSource);
            actionButton3.Command = ActionEvent.Command.PRESS_COMPLETELY;

            actionButton2.SetActionSource(ref _actionSource);
            actionButton2.Command = ActionEvent.Command.PRESS_HALFWAY;

            actionButton4.SetActionSource(ref _actionSource);
            actionButton4.Command = ActionEvent.Command.PRESS_OFF;

            actionButton5.SetActionSource(ref _actionSource);
            actionButton5.Command = ActionEvent.Command.START_EVF;

            actionButton6.SetActionSource(ref _actionSource);
            actionButton6.Command = ActionEvent.Command.END_EVF;

            actionButton10.SetActionSource(ref _actionSource);
            actionButton10.Command = ActionEvent.Command.FOCUS_NEAR3;

            actionButton11.SetActionSource(ref _actionSource);
            actionButton11.Command = ActionEvent.Command.FOCUS_NEAR2;

            actionButton12.SetActionSource(ref _actionSource);
            actionButton12.Command = ActionEvent.Command.FOCUS_NEAR1;

            actionButton13.SetActionSource(ref _actionSource);
            actionButton13.Command = ActionEvent.Command.FOCUS_FAR1;

            actionButton14.SetActionSource(ref _actionSource);
            actionButton14.Command = ActionEvent.Command.FOCUS_FAR2;

            actionButton15.SetActionSource(ref _actionSource);
            actionButton15.Command = ActionEvent.Command.FOCUS_FAR3;

            actionButton7.SetActionSource(ref _actionSource);
            actionButton7.Command = ActionEvent.Command.EVF_AF_ON;

            actionButton8.SetActionSource(ref _actionSource);
            actionButton8.Command = ActionEvent.Command.EVF_AF_OFF;

            actionButton9.SetActionSource(ref _actionSource);
            actionButton9.Command = ActionEvent.Command.ZOOM_FIT;

            actionButton16.SetActionSource(ref _actionSource);
            actionButton16.Command = ActionEvent.Command.ZOOM_ZOOM;

            actionButton17.SetActionSource(ref _actionSource);
            actionButton17.Command = ActionEvent.Command.POSITION_UP;

            actionButton18.SetActionSource(ref _actionSource);
            actionButton18.Command = ActionEvent.Command.POSITION_LEFT;

            actionButton19.SetActionSource(ref _actionSource);
            actionButton19.Command = ActionEvent.Command.POSITION_RIGHT;

            actionButton20.SetActionSource(ref _actionSource);
            actionButton20.Command = ActionEvent.Command.POSITION_DOWN;

            actionButton21.SetActionSource(ref _actionSource);
            actionButton21.Command = ActionEvent.Command.REC_START;

            actionButton22.SetActionSource(ref _actionSource);
            actionButton22.Command = ActionEvent.Command.REC_END;

            actionButton23.SetActionSource(ref _actionSource);
            actionButton23.Command = ActionEvent.Command.ROLLPITCH;
            actionButton23.Text = "Roll Pitch On";

            actionButton24.SetActionSource(ref _actionSource);
            actionButton24.Command = ActionEvent.Command.CLICK_WB;

            actionButton25.SetActionSource(ref _actionSource);
            actionButton25.Command = ActionEvent.Command.CLICK_AF_POINT;

            actionRadioButton1.SetActionSource(ref _actionSource);
            actionRadioButton1.Command = ActionEvent.Command.PRESS_STILL;
            updateFixedMovie(_controller.GetModel().FixedMovie);

            actionRadioButton2.SetActionSource(ref _actionSource);
            actionRadioButton2.Command = ActionEvent.Command.PRESS_MOVIE;
            updateFixedMovie(_controller.GetModel().FixedMovie);

            actionRadioButton3.SetActionSource(ref _actionSource);
            actionRadioButton3.Command = ActionEvent.Command.MIRRORUP_ON;

            actionRadioButton4.SetActionSource(ref _actionSource);
            actionRadioButton4.Command = ActionEvent.Command.MIRRORUP_OFF;


            // Check Mirror Up Setting.
            if (0xffffffff == _controller.GetModel().MirrorUpSetting || (_controller.GetModel().StartupEvfOutputDevice & EDSDKLib.EDSDK.EvfOutputDevice_TFT) != 0)
            {
                actionRadioButton3.Enabled = false;
                actionRadioButton4.Enabled = false;
            }
            updateMirrorLockUpState(_controller.GetModel().MirrorLockUpState);

            controlFocusButton((int)EDSDKLib.EDSDK.EdsEvfAFMode.Evf_AFMode_LiveFace != _controller.GetModel().EvfAFMode);

            // invalidate it in the DC
            label26.Enabled = _controller.GetModel().isTypeDS;
            actionButton9.Enabled = _controller.GetModel().isTypeDS;
            actionButton16.Enabled = _controller.GetModel().isTypeDS;
            label19.Enabled = _controller.GetModel().isTypeDS;
            // Processing inside updateFixedMovie
            //actionButton10.Enabled = _controller.GetModel().isTypeDS;
            //actionButton11.Enabled = _controller.GetModel().isTypeDS;
            //actionButton12.Enabled = _controller.GetModel().isTypeDS;
            //actionButton13.Enabled = _controller.GetModel().isTypeDS;
            //actionButton14.Enabled = _controller.GetModel().isTypeDS;
            //actionButton15.Enabled = _controller.GetModel().isTypeDS;

            // invalidate it in the DS
            label15.Enabled = !_controller.GetModel().isTypeDS;
            zoom1.Enabled = false; // At the time of start, ZoomBar is off
            label16.Enabled = !_controller.GetModel().isTypeDS;

            e = new CameraEvent(CameraEvent.Type.PROPERTY_CHANGED, (IntPtr)EDSDKLib.EDSDK.PropID_Evf_AFMode);
            _controller.GetModel().NotifyObservers(e);

            e = new CameraEvent(CameraEvent.Type.PROPERTY_CHANGED, (IntPtr)EDSDKLib.EDSDK.PropID_AvailableShots);
            _controller.GetModel().NotifyObservers(e);

            e = new CameraEvent(CameraEvent.Type.PROPERTY_CHANGED, (IntPtr)EDSDKLib.EDSDK.PropID_BatteryLevel);
            _controller.GetModel().NotifyObservers(e);

            e = new CameraEvent(CameraEvent.Type.PROPERTY_CHANGED, (IntPtr)EDSDKLib.EDSDK.PropID_TempStatus);
            _controller.GetModel().NotifyObservers(e);

            e = new CameraEvent(CameraEvent.Type.PROPERTY_CHANGED, (IntPtr)EDSDKLib.EDSDK.PropID_FixedMovie);
            _controller.GetModel().NotifyObservers(e);

            if (!_controller.GetModel().isTypeDS)
            {
                _actionSource.FireEvent(ActionEvent.Command.REMOTESHOOTING_START, IntPtr.Zero);
            }

            updateAngleInfoLabel("-", "-", "-");
        }

        private void RemoteCapture_FormClosing(object sender, FormClosingEventArgs e)
        {
            Application.DoEvents();
            _actionSource.FireEvent(ActionEvent.Command.END_ROLLPITCH, IntPtr.Zero);
            _actionSource.FireEvent(ActionEvent.Command.END_EVF, IntPtr.Zero);
            if (!_controller.GetModel().isTypeDS)
            {
                _actionSource.FireEvent(ActionEvent.Command.REMOTESHOOTING_STOP, IntPtr.Zero);
            }
            _actionSource.FireEvent(ActionEvent.Command.PRESS_OFF, IntPtr.Zero);
            _actionSource.FireEvent(ActionEvent.Command.EVF_AF_OFF, IntPtr.Zero);
            _observerList.ForEach(observer => _controller.GetModel().Remove(ref observer));
        }

        private void zoom1_ValueChanged(object sender, EventArgs e)
        {
            label16.Text = zoom1.Value.ToString();
        }

        private void actionButton5_Click(object sender, EventArgs e)
        {
            if (!_controller.GetModel().isTypeDS)
            {
                zoom1.Enabled = true;
            }
        }

        private void actionButton6_Click(object sender, EventArgs e)
        {
            zoom1.Enabled = false;
        }

        public void controlFocusButton(bool onoff)
        {
            if (this.InvokeRequired)
            {
                this.Invoke(new Action(() => controlFocusButton(onoff)), null);
            }
            else
            {
                actionButton17.Enabled = onoff;
                actionButton18.Enabled = onoff;
                actionButton19.Enabled = onoff;
                actionButton20.Enabled = onoff;
            }
        }

        public void updateAngleInfoLabel(string pos, string roll, string pitc)
        {
            if (this.InvokeRequired)
            {
                this.Invoke(new Action(() => updateAngleInfoLabel(pos, roll, pitc)), null);
            }
            else
            {
                label22.Text = pos;
                label23.Text = roll;
                label25.Text = pitc;

                if (_controller.GetModel().RollPitch == 0)
                {
                    actionButton23.Text = "Roll Pitch Off";
                }
                else
                {
                    actionButton23.Text = "Roll Pitch On";
                }
            }
        }

        public void changeMouseCursor(bool onoff)
        {
            if (this.InvokeRequired)
            {
                this.Invoke(new Action(() => changeMouseCursor(onoff)), null);
            }
            else
            {
                if (onoff)
                {
                    Cursor = Cursors.Cross;
                    _clip = Cursor.Clip;
                    Rectangle limitRect = evfPictureBox1.Bounds;
                    limitRect.X = limitRect.X + this.DesktopLocation.X + 10;
                    limitRect.Y = limitRect.Y + this.DesktopLocation.Y + 30;
                    Cursor.Clip = limitRect;
                }
                else
                {
                    Cursor = Cursors.Default;
                    Cursor.Clip = _clip;
                }
            }
        }

        private void evfPictureBox1_MouseClick(object sender, MouseEventArgs e)
        {
            if (Cursor == Cursors.Cross)
            {
                // JPEG L size
                int JpegLWidth = 6720;
                int JpegLHeight = 4480;
                if (_controller.GetModel().SizeJpegLarge.width != 0 && _controller.GetModel().SizeJpegLarge.height != 0)
                {
                    JpegLWidth = _controller.GetModel().SizeJpegLarge.width;
                    JpegLHeight = _controller.GetModel().SizeJpegLarge.height;
                }

                EDSDKLib.EDSDK.EdsPoint clickPoint;

                clickPoint.x = (int)((double)JpegLWidth / (double)evfPictureBox1.Width * (double)e.X);
                clickPoint.y = (int)((double)JpegLHeight / (double)evfPictureBox1.Height * (double)e.Y);
                if (clickPoint.x > JpegLWidth - 1)
                {
                    clickPoint.x = JpegLWidth - 1;
                }
                else if (clickPoint.x < 0)
                {
                    clickPoint.x = 0;
                }
                if (clickPoint.y > JpegLHeight - 1)
                {
                    clickPoint.y = JpegLHeight - 1;
                }
                else if (clickPoint.y < 0)
                {
                    clickPoint.y = 0;
                }

                _controller.GetModel().ClickPoint = clickPoint.x << 16 | clickPoint.y;
                _controller.GetModel().NotifyObservers(new CameraEvent(CameraEvent.Type.MOUSE_CURSOR, (IntPtr)0));
            }
        }

        public void updateFixedMovie(uint data)
        {
            if (this.InvokeRequired)
            {
                this.Invoke(new Action(() => updateFixedMovie(data)), null);
            }
            else
            {
                if (data == 0)
                {
                    actionRadioButton1.Checked = true;

                    // Rec Button
                    actionButton21.Enabled = false;
                    actionButton22.Enabled = false;

                    // MovieQuality
                    movieQuality1.Enabled = false;

                    if (_controller.GetModel().isTypeDS)
                    {
                        actionButton10.Enabled = true;
                        actionButton11.Enabled = true;
                        actionButton12.Enabled = true;
                        actionButton13.Enabled = true;
                        actionButton14.Enabled = true;
                        actionButton15.Enabled = true;
                    }

                    // Clear EVF
                    this.evfPictureBox1.Image = null;
                    _actionSource.FireEvent(ActionEvent.Command.END_EVF, IntPtr.Zero);
                }
                else
                {
                    actionRadioButton2.Checked = true;
                    
                    // Rec Button
                    actionButton21.Enabled = true;
                    actionButton22.Enabled = true;

                    // MovieQuality
                    movieQuality1.Enabled = true;

                    actionButton10.Enabled = false;
                    actionButton11.Enabled = false;
                    actionButton12.Enabled = false;
                    actionButton13.Enabled = false;
                    actionButton14.Enabled = false;
                    actionButton15.Enabled = false;
                }
            }
        }

        public void updateMirrorLockUpState(uint data)
        {
            if (this.InvokeRequired)
            {
                this.Invoke(new Action(() => updateMirrorLockUpState(data)), null);
            }
            else
            {
                if (data != (uint)EDSDKLib.EDSDK.EdsMirrorLockupState.Disable)
                {
                    // Enable = 1, DuringShooting = 2
                    actionRadioButton3.Checked = true;
                }
                else
                {
                    // Disable = 0
                    actionRadioButton4.Checked = true;
                }
            }
        }

        private void RemoteCapture_Load(object sender, EventArgs e)
        {

        }

    }
}
