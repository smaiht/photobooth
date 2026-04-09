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
using System.Drawing;
using System.Runtime.InteropServices;

namespace CameraControl
{
    class EvfPictureBox : System.Windows.Forms.PictureBox, IObserver
    {
        static ImageConverter imgconv = new ImageConverter();

        private CameraModel _model;

        private bool _active;

        private bool m_bDrawZoomFrame;

        private EDSDKLib.EDSDK.EdsRect vRect;

        private EDSDKLib.EDSDK.EdsFocusInfo m_focusInfo;

        private ActionSource _actionSource;
        public void SetActionSource(ref ActionSource actionSource) { _actionSource = actionSource; }

        public EvfPictureBox()
        {
            _active = false;
        }

        private delegate void _Update(Observable from, CameraEvent e);

        public void Update(Observable from, CameraEvent e)
        {

            if (this.InvokeRequired)
            {
                //The update processing can be executed from another thread. 
                this.Invoke(new _Update(Update), new object[] { from, e });
                return;
            }

            CameraEvent.Type eventType = e.GetEventType();
            _model = (CameraModel)from;
            uint propertyID;
            switch (eventType)
            {
                case CameraEvent.Type.EVFDATA_CHANGED:
                    IntPtr evfDataSetPtr = e.GetArg();

                    EVFDataSet evfDataSet = (EVFDataSet)Marshal.PtrToStructure(evfDataSetPtr, typeof(EVFDataSet));

                    this.OnDrawImage(evfDataSet);

                    propertyID = EDSDKLib.EDSDK.PropID_FocusInfo;

                    _actionSource.FireEvent(ActionEvent.Command.GET_PROPERTY, (IntPtr)propertyID);

                    _actionSource.FireEvent(ActionEvent.Command.DOWNLOAD_EVF, IntPtr.Zero);

                    break;

                case CameraEvent.Type.PROPERTY_CHANGED:
                    propertyID = (uint)e.GetArg();

                    if (propertyID == EDSDKLib.EDSDK.PropID_Evf_OutputDevice)
                    {
                        uint device = _model.EvfOutputDevice;

                        // PC live view has started.
                        if (!_active && (device & EDSDKLib.EDSDK.EvfOutputDevice_PC) != 0)
                        {
                            _active = true;
                            // Start download of image data.
                            _actionSource.FireEvent(ActionEvent.Command.DOWNLOAD_EVF, IntPtr.Zero);
                        }

                        // PC live view has ended.
                        if (_active && (device & EDSDKLib.EDSDK.EvfOutputDevice_PC) == 0)
                        {
                            _active = false;
                        }
                    }
            

                    else if (propertyID == EDSDKLib.EDSDK.PropID_FocusInfo && this.Image != null)
                    {
                        float xRatio = 1;
                        float yRatio = 1;

                        m_focusInfo = _model.FocusInfo;

                        xRatio = (float)(this.Image.Width) / (float)(m_focusInfo.imageRect.width);
                        yRatio = (float)(this.Image.Height) / (float)(m_focusInfo.imageRect.height);
                        for (uint i = 0; i < m_focusInfo.pointNumber; i++)
                        {
                            m_focusInfo.focusPoint[i].rect.x = (int)(m_focusInfo.focusPoint[i].rect.x * xRatio);
                            m_focusInfo.focusPoint[i].rect.y = (int)(m_focusInfo.focusPoint[i].rect.y * yRatio);
                            m_focusInfo.focusPoint[i].rect.width = (int)(m_focusInfo.focusPoint[i].rect.width * xRatio);
                            m_focusInfo.focusPoint[i].rect.height = (int)(m_focusInfo.focusPoint[i].rect.height * yRatio);
                        }
                    }

                    else if (propertyID == EDSDKLib.EDSDK.PropID_Evf_AFMode)
                    {
                        m_bDrawZoomFrame = _model.EvfAFMode != 2 && _model.isTypeDS;
                    }

                    break;
            }
        }
        private void OnDrawImage(EVFDataSet evfDataSet)
        {
            IntPtr evfStream;
            UInt64 streamLength;

            EDSDKLib.EDSDK.EdsGetPointer(evfDataSet.stream, out evfStream);
            EDSDKLib.EDSDK.EdsGetLength(evfDataSet.stream, out streamLength);

            vRect = _model.VisibleRect;
            SolidBrush black = new SolidBrush(Color.Black);

            byte[] data = new byte[(int)streamLength];
            Marshal.Copy(evfStream, data, 0, (int)streamLength);
            Image img = (Image)imgconv.ConvertFrom(data);
            Bitmap canvas = new Bitmap(img);

            int iWidth = canvas.Width;
            int iHeight = canvas.Height;

            Graphics g = Graphics.FromImage(canvas);

            g.DrawImage(img, 0, 0);

            //when aspect ratio is 1:1 or 4:3
            if((_model.Aspect == 1) || (_model.Aspect == 2))
            {
                float hvRatio = (float)vRect.width / vRect.height;
                int rWidth =  (int)(iWidth - iHeight * hvRatio) / 2;
      
                Rectangle rectLeft = new Rectangle(0, 0, rWidth, iHeight);
                Rectangle rectRight = new Rectangle((int)(rWidth + iHeight * hvRatio), 0, rWidth, iHeight);
                g.FillRectangle(black, rectLeft);
                g.FillRectangle(black, rectRight);

            }

            //when aspect ratio is 16:9
            if(_model.Aspect == 7)
            {
                float vhRatio = (float)vRect.height / vRect.width;
                int rHeight = (int)(iHeight - iWidth * vhRatio) / 2;

                Rectangle rectTop = new Rectangle(0, 0, iWidth, rHeight);
                Rectangle rectBottom = new Rectangle(0, (int)(rHeight + iWidth * vhRatio), iWidth, rHeight);
                g.FillRectangle(black, rectTop);
                g.FillRectangle(black, rectBottom);
            }

            // Display the focus border if displaying the entire image.
            if (evfDataSet.zoom == 1 && (evfDataSet.sizeJpegLarge.width != 0 && evfDataSet.sizeJpegLarge.height != 0))
            {
                OnDrawFocusRect(ref g, ref evfDataSet, ref iWidth, ref iHeight);
            }

            g.Dispose();
            if (_model.isEvfEnable)
            {
                this.Image = canvas;
            }
            else
            {
                this.Image = null;
            }
        }

        private void OnDrawFocusRect(ref Graphics g, ref EVFDataSet evfDataSet, ref int iWidth, ref int iHeight)
        {

            // Draw Zoom Frame
            if (m_bDrawZoomFrame)
            {
                int cx = iWidth;
                int cy = iHeight;

                // The zoomPosition is given by the coordinates of the upper left of the focus border using Jpeg Large size as a reference.

                // The size of the focus border is one fifth the size of Jpeg Large.
                // Because the image fills the entire window, the height and width to be drawn is one fifth of the window size.

                int iw = evfDataSet.sizeJpegLarge.width;
                int ih = evfDataSet.sizeJpegLarge.height;

                long left = evfDataSet.zoomRect.x;
                long top  = evfDataSet.zoomRect.y;

                long x = left * cx / iw;
                long y = top  * cy / ih;

                long width  = evfDataSet.zoomRect.width  * cx / iw;
                long height = evfDataSet.zoomRect.height * cy / ih;

                // Draw.
                Pen pen = new Pen(Color.FromArgb(255, 255, 255));
                pen.Width = 3;

                g.DrawRectangle(pen, x, y, width, height);
            }

            Pen defaultPen = new Pen(Color.FromArgb(255, 255, 255));
            defaultPen.Width = 3;
            Pen errPen = new Pen(Color.FromArgb(255, 0, 0));
            errPen.Width = 3;
            Pen servoPen = new Pen(Color.FromArgb(65, 148, 232));
            servoPen.Width = 3;
            Pen justPen = new Pen(Color.FromArgb(0, 255, 0));
            justPen.Width = 3;
            Pen disablePen = new Pen(Color.FromArgb(128, 128, 128));
            disablePen.Width = 3;

            Pen oldPenH;

            Rectangle afRect = new Rectangle(0, 0, 0, 0);
            for (uint i = 0; i < m_focusInfo.pointNumber; i++)
            {
                if (m_focusInfo.focusPoint[i].valid == 1)
                {
                    // Selecte Just Focus Pen
                    if ((m_focusInfo.focusPoint[i].justFocus & 0x0f) == 1)
                    {
                        oldPenH = justPen;
                    }
                    else if ((m_focusInfo.focusPoint[i].justFocus & 0x0f) == 2)
                    {
                        oldPenH = errPen;
                    }
                    else if ((m_focusInfo.focusPoint[i].justFocus & 0x0f) == 4)
                    {
                        oldPenH = servoPen;
                    }
                    else
                    {
                        oldPenH = defaultPen;
                    }
                    if (m_focusInfo.focusPoint[i].selected != 1)
                    {
                        oldPenH = disablePen;
                    }
                    // Set Frame Rect                   
                    afRect.X = m_focusInfo.focusPoint[i].rect.x;
                    afRect.Y = m_focusInfo.focusPoint[i].rect.y;
                    afRect.Width = m_focusInfo.focusPoint[i].rect.width;
                    afRect.Height = m_focusInfo.focusPoint[i].rect.height;
                    g.DrawRectangle(oldPenH, afRect);
                }
            }
        }
    }
}

 


