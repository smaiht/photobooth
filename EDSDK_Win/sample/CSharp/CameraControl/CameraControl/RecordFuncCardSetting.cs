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
using System.ComponentModel;
using System.Data;
using System.Drawing;
using System.Linq;
using System.Text;
using System.Threading.Tasks;
using System.Windows.Forms;

namespace CameraControl
{
    public partial class RecordFuncCardSetting : Form
    {
        CameraController _controller = null;
        IntPtr _camera = (IntPtr)0;
        private EDSDKLib.EDSDK.EdsPropertyDesc _desc1;
        private EDSDKLib.EDSDK.EdsPropertyDesc _desc2;
        private EDSDKLib.EDSDK.EdsPropertyDesc _desc3;
        private EDSDKLib.EDSDK.EdsPropertyDesc _desc4;
        private EDSDKLib.EDSDK.EdsPropertyDesc _desc5;

        //      int size;
        //      private EDSDKLib.EDSDK.EdsDataType datatype;

        uint _StillMovieDivideSetting;
        uint _StillMovieDivideSettingPrev;
        uint _CardExtension;
        uint _CardExtensionPrev;
        uint _MovieCardExtension;
        uint _MovieCardExtensionPrev;
        uint _StillCurrentMedia;
        uint _StillCurrentMediaPrev;
        uint _MovieCurrentMedia;
        uint _MovieCurrentMediaPrev;


        protected Dictionary<uint, string> map1 = new Dictionary<uint, string>();
        protected Dictionary<uint, string> map2 = new Dictionary<uint, string>();
        protected Dictionary<uint, string> map3 = new Dictionary<uint, string>();
        protected Dictionary<uint, string> map4 = new Dictionary<uint, string>();

        public RecordFuncCardSetting(ref CameraController controller)
        {

            map1.Add(0x00000000, "Disable");
            map1.Add(0x00000001, "Enable");
            map1.Add(0xffffffff, "unknown");

            map2.Add(0x00000000, "Standard");
            map2.Add(0x00000001, "Rec. to multiple");
            map2.Add(0x00000002, "Rec. separately");
            map2.Add(0x00000003, "Auto switch card");
            map2.Add(0xffffffff, "unknown");

            map3.Add(0x00000000, "Enable");
            map3.Add(0x00000001, "slot1");
            map3.Add(0x00000002, "slot2");
            map3.Add(0xffffffff, "unknown");

            map4.Add(0x00000000, "Standard");
            map4.Add(0x00000001, "Rec. to multiple");
            map4.Add(0x00000002, "slot1=RAW and slot2=MP4");
            map4.Add(0x00000003, "Auto switch card");
            map4.Add(0xffffffff, "unknown");

            _controller = controller;
            _camera = _controller.GetModel().Camera;
            InitializeComponent();


      


            _desc1 = new EDSDKLib.EDSDK.EdsPropertyDesc();
            uint err = EDSDKLib.EDSDK.EdsGetPropertyData(_camera, EDSDKLib.EDSDK.PropID_StillMovieDivideSetting, 0, out _StillMovieDivideSetting);
            err = EDSDKLib.EDSDK.EdsGetPropertyDesc(_camera, EDSDKLib.EDSDK.PropID_StillMovieDivideSetting, out _desc1);

            this.comboBox1.Items.Clear();
            for (int i = 0; i < _desc1.NumElements; i++)
            {
                string outString;
                bool isGet = map1.TryGetValue((uint)_desc1.PropDesc[i], out outString);
                if (isGet && !outString.Equals("unknown"))
                {
                    // Create list of combo box
                    comboBox1.Items.Add(outString);
                    if (_StillMovieDivideSetting == _desc1.PropDesc[i])
                    {
                        // Select item of combo box
                        comboBox1.SelectedIndex = i;
                        _StillMovieDivideSetting = (uint)_desc1.PropDesc[i];
                        _StillMovieDivideSettingPrev = _StillMovieDivideSetting;
                    }
                }

            }


            _desc2 = new EDSDKLib.EDSDK.EdsPropertyDesc();
            err = EDSDKLib.EDSDK.EdsGetPropertyData(_camera, EDSDKLib.EDSDK.PropID_CardExtension, 0, out _CardExtension);
            err = EDSDKLib.EDSDK.EdsGetPropertyDesc(_camera, EDSDKLib.EDSDK.PropID_CardExtension, out _desc2);
            this.comboBox2.Items.Clear();
            for (int i = 0; i < _desc2.NumElements; i++)
            {
                string outString;
                bool isGet = map2.TryGetValue((uint)_desc2.PropDesc[i], out outString);
                if (isGet && !outString.Equals("unknown"))
                {
                    // Create list of combo box
                    comboBox2.Items.Add(outString);
                    if (_CardExtension == _desc2.PropDesc[i])
                    {
                        // Select item of combo box
                        comboBox2.SelectedIndex = i;
                        _CardExtension = (uint)_desc2.PropDesc[i];
                        _CardExtensionPrev = _CardExtension;
                    }
                }

            }

            _desc3 = new EDSDKLib.EDSDK.EdsPropertyDesc();
            err = EDSDKLib.EDSDK.EdsGetPropertyData(_camera, EDSDKLib.EDSDK.PropID_StillCurrentMedia, 0, out _StillCurrentMedia);
            err = EDSDKLib.EDSDK.EdsGetPropertyDesc(_camera, EDSDKLib.EDSDK.PropID_StillCurrentMedia, out _desc3);
            this.comboBox3.Items.Clear();
            for (int i = 0; i < _desc3.NumElements; i++)
            {
                string outString;
                bool isGet = map3.TryGetValue((uint)_desc3.PropDesc[i], out outString);
                if (isGet && !outString.Equals("unknown"))
                {
                    // Create list of combo box
                    comboBox3.Items.Add(outString);
                    if (_StillCurrentMedia == _desc3.PropDesc[i])
                    {
                        // Select item of combo box
                        comboBox3.SelectedIndex = i;
                        _StillCurrentMedia = (uint)_desc3.PropDesc[i];
                        _StillCurrentMediaPrev = _StillCurrentMedia;
                    }
                }

            }
            _desc4 = new EDSDKLib.EDSDK.EdsPropertyDesc();
            err = EDSDKLib.EDSDK.EdsGetPropertyData(_camera, EDSDKLib.EDSDK.PropID_MovieCardExtension, 0, out _MovieCardExtension);
            err = EDSDKLib.EDSDK.EdsGetPropertyDesc(_camera, EDSDKLib.EDSDK.PropID_MovieCardExtension, out _desc4);
            this.comboBox4.Items.Clear();
            for (int i = 0; i < _desc4.NumElements; i++)
            {
                string outString;
                bool isGet = map4.TryGetValue((uint)_desc4.PropDesc[i], out outString);
                if (isGet && !outString.Equals("unknown"))
                {
                    // Create list of combo box
                    comboBox4.Items.Add(outString);
                    if (_MovieCardExtension == _desc4.PropDesc[i])
                    {
                        // Select item of combo box
                        comboBox4.SelectedIndex = i;
                        _MovieCardExtension = (uint)_desc4.PropDesc[i];
                        _MovieCardExtensionPrev = _MovieCardExtension;
                    }
                }
            }

            _desc5 = new EDSDKLib.EDSDK.EdsPropertyDesc();
            err = EDSDKLib.EDSDK.EdsGetPropertyData(_camera, EDSDKLib.EDSDK.PropID_MovieCurrentMedia, 0, out _MovieCurrentMedia);
            err = EDSDKLib.EDSDK.EdsGetPropertyDesc(_camera, EDSDKLib.EDSDK.PropID_MovieCurrentMedia, out _desc5);
            this.comboBox5.Items.Clear();
            for (int i = 0; i < _desc5.NumElements; i++)
            {
                string outString;
                bool isGet = map3.TryGetValue((uint)_desc5.PropDesc[i], out outString);
                if (isGet && !outString.Equals("unknown"))
                {
                    // Create list of combo box
                    comboBox5.Items.Add(outString);
                    if (_MovieCurrentMedia == _desc5.PropDesc[i])
                    {
                        // Select item of combo box
                        comboBox5.SelectedIndex = i;
                        _MovieCurrentMedia = (uint)_desc5.PropDesc[i];
                        _MovieCurrentMediaPrev = _MovieCurrentMedia;
                    }
                }
            }


        }

        private void RecordFuncCardSetting_Load(object sender, EventArgs e)
        {

        }

        private void comboBox1_SelectedIndexChanged(object sender, EventArgs e)
        {

        }

        private void comboBox1_SelectionChangeCommitted(object sender, EventArgs e)
        {
          
            uint key = (uint)_desc1.PropDesc[comboBox1.SelectedIndex];
            uint err = EDSDKLib.EDSDK.EdsSetPropertyData(_camera, EDSDKLib.EDSDK.PropID_StillMovieDivideSetting, 0, sizeof(uint), key);
            var _recordFuncCardSetting = new RecordFuncCardSetting(ref _controller);

        }

        private void comboBox2_SelectedIndexChanged(object sender, EventArgs e)
        {

        }

        private void comboBox2_SelectionChangeCommitted(object sender, EventArgs e)
        {
            uint key = (uint)_desc2.PropDesc[comboBox2.SelectedIndex];
            uint err = EDSDKLib.EDSDK.EdsSetPropertyData(_controller.GetModel().Camera, EDSDKLib.EDSDK.PropID_CardExtension, 0, sizeof(uint), key);
          
        }

        private void comboBox3_SelectedIndexChanged(object sender, EventArgs e)
        {

        }

        private void comboBox3_SelectionChangeCommitted(object sender, EventArgs e)
        {
            uint key = (uint)_desc3.PropDesc[comboBox3.SelectedIndex];
            uint err = EDSDKLib.EDSDK.EdsSetPropertyData(_controller.GetModel().Camera, EDSDKLib.EDSDK.PropID_StillCurrentMedia, 0, sizeof(uint), key);
         
        }

        private void comboBox4_SelectedIndexChanged(object sender, EventArgs e)
        {

        }

        private void comboBox4_SelectionChangeCommitted(object sender, EventArgs e)
        {
            uint key = (uint)_desc4.PropDesc[comboBox4.SelectedIndex];
            uint err = EDSDKLib.EDSDK.EdsSetPropertyData(_controller.GetModel().Camera, EDSDKLib.EDSDK.PropID_MovieCardExtension, 0, sizeof(uint), key);
        
        }

        private void comboBox5_SelectedIndexChanged(object sender, EventArgs e)
        {

        }

        private void comboBox5_SelectionChangeCommitted(object sender, EventArgs e)
        {
            uint key = (uint)_desc5.PropDesc[comboBox5.SelectedIndex];
            uint err = EDSDKLib.EDSDK.EdsSetPropertyData(_controller.GetModel().Camera, EDSDKLib.EDSDK.PropID_MovieCurrentMedia, 0, sizeof(uint), key);
            
        }
    }
}
