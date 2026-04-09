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
using System.Security.Permissions;

namespace CameraControl
{

    public partial class Progress : Form, IObserver
    {
        CameraController _controller = null;
        private Progress frmProgress;
        private int _max;
        private int _val;

        public Progress(ref CameraController controller)
        {
            IObserver iObs = this;

            InitializeComponent();
            frmProgress = this;
            _controller = controller;

        }

        ~Progress()
        {
            //Do not called at the appropiate time.

        }

        public Progress getFormProgress { get { return frmProgress; } }

        public void Maximum(int max)
        {
            Maximum(max);
        }

        public void Update(Observable from, CameraEvent e)
        {
            Update(e);
        }

        private delegate void _Update(CameraEvent e);

        private void Update(CameraEvent e)
        {
            if (this.InvokeRequired)
            {
                //The update processing can be executed from another thread. 
                this.Invoke(new _Update(Update), new object[] { e });
                return;
            }

            CameraEvent.Type eventType = e.GetEventType();

            switch (eventType)
            {
                case CameraEvent.Type.DOWNLOAD_START:
                    System.Threading.Thread.Sleep(500);
                    _max = (int)e.GetArg();
                    _val = 0;

                    frmProgress.progressBar1.Maximum = _max;
                    frmProgress.progressBar1.Value = _val;
                    frmProgress.label2.Text = "File Downloading ...";
                    _controller.GetModel()._ExecuteStatus = CameraModel.Status.DOWNLOADING;
                    frmProgress.label1.Text = _val.ToString() + " / " + _max.ToString();
                    break;
                case CameraEvent.Type.DELETE_START:
                    System.Threading.Thread.Sleep(500);
                    _max = (int)e.GetArg();
                    _val = 0;

                    frmProgress.progressBar1.Maximum = _max;
                    frmProgress.progressBar1.Value = _val;
                    frmProgress.label2.Text = "File Deleting ...";
                    _controller.GetModel()._ExecuteStatus = CameraModel.Status.DELETEING;
                    frmProgress.label1.Text = _val.ToString() + " / " + _max.ToString();
                    break;
                case CameraEvent.Type.PROGRESS_REPORT:
                    _val++;
                    frmProgress.progressBar1.Value = _val;
                    frmProgress.progressBar1.Invalidate();
                    frmProgress.label1.Text = _val.ToString() + " / " + _max.ToString();
                    break;
                case CameraEvent.Type.DOWNLOAD_COMPLETE:
                case CameraEvent.Type.DELETE_COMPLETE:
                    // Proceed the last progress.
                    frmProgress.Refresh();
                    System.Threading.Thread.Sleep(500);
                    // Close progress .
                    frmProgress.Close();
                    frmProgress.Dispose();
                    _controller.GetModel()._ExecuteStatus = (int)CameraModel.Status.NONE;

                    break;
                case CameraEvent.Type.SHUT_DOWN:
                    CameraModel cameramodel = _controller.GetModel();
                    cameramodel._ExecuteStatus = CameraModel.Status.CANCELING;
                    frmProgress.label2.Text = "Canceling ...";
                    frmProgress.Invalidate();

                    break;
                default:
                    break;
            }
        }

        private void button2_Click(object sender, EventArgs e)
        {

            CameraModel cameramodel = _controller.GetModel();
            cameramodel._ExecuteStatus = CameraModel.Status.CANCELING;
            frmProgress.label2.Text = "Canceling ...";
            frmProgress.Invalidate();
        }

        private void FormProgress_FormClosing(object sender, FormClosingEventArgs e)
        {
            CameraModel cameramodel = _controller.GetModel();
            cameramodel._ExecuteStatus = CameraModel.Status.CANCELING;
        }

        protected override CreateParams CreateParams
        {
            [SecurityPermission(SecurityAction.Demand,
                Flags = SecurityPermissionFlag.UnmanagedCode)]
            get
            {
                const int CS_NOCLOSE = 0x200;
                CreateParams cp = base.CreateParams;
                cp.ClassStyle = cp.ClassStyle | CS_NOCLOSE;

                return cp;
            }
        }
    }

}
