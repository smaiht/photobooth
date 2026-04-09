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
using System.Runtime.InteropServices;
using System.Windows.Forms;
using System.Globalization;

namespace CameraControl
{
    public partial class DateTimeZoneSetting : Form
    {
        CameraController _controller = null;
        IntPtr _camera = (IntPtr)0;
        string _localTime;
        string _localTimePrev;
        uint _timeZone;
        uint _timeZonePrev;
        bool _summerTimeSetting = false;
        bool _summerTimeSettingPrev = false;
        private EDSDKLib.EDSDK.EdsPropertyDesc _desc;
        protected Dictionary<uint, string> map = new Dictionary<uint, string>();

        public DateTimeZoneSetting(ref CameraController controller)
        {
            map.Add(0x00000000, "None");
            map.Add(0x00000001, "Chatham Islands");
            map.Add(0x00000002, "Wellington");
            map.Add(0x00000003, "Solomon Islands");
            map.Add(0x00000004, "Sydney");
            map.Add(0x00000005, "Adelaide");
            map.Add(0x00000006, "Tokyo");
            map.Add(0x00000007, "Hong Kong");
            map.Add(0x00000008, "Bangkok");
            map.Add(0x00000009, "Yangon");
            map.Add(0x0000000A, "Dhaka");
            map.Add(0x0000000B, "Kathmandu");
            map.Add(0x0000000C, "Delhi");
            map.Add(0x0000000D, "Karachi");
            map.Add(0x0000000E, "Kabul");
            map.Add(0x0000000F, "Dubai");
            map.Add(0x00000010, "Tehran");
            map.Add(0x00000011, "Moscow");
            map.Add(0x00000012, "Cairo");
            map.Add(0x00000013, "Paris");
            map.Add(0x00000014, "London");
            map.Add(0x00000015, "Azores");
            map.Add(0x00000016, "Fernando");
            map.Add(0x00000017, "Sao Paulo");
            map.Add(0x00000018, "Newfoundland");
            map.Add(0x00000019, "Santiago");
            map.Add(0x0000001A, "Caracas");
            map.Add(0x0000001B, "New York");
            map.Add(0x0000001C, "Chicago");
            map.Add(0x0000001D, "Denver");
            map.Add(0x0000001E, "Los Angeles");
            map.Add(0x0000001F, "Anchorage");
            map.Add(0x00000020, "Honolulu");
            map.Add(0x00000021, "Samoa");
            map.Add(0x00000022, "Riyadh");
            map.Add(0x00000023, "Manaus");
            map.Add(0x00000100, "UTC");
            map.Add(0xffffffff, "unknown");

            _controller = controller;
            _camera = _controller.GetModel().Camera;

            InitializeComponent();

            // Date / Time
            EDSDKLib.EDSDK.EdsTime utcTime;
            uint err = EDSDKLib.EDSDK.EdsGetPropertyData(_camera, EDSDKLib.EDSDK.PropID_UTCTime, 0, out utcTime);

            // Zone Setting
            err = EDSDKLib.EDSDK.EdsGetPropertyData(_camera, EDSDKLib.EDSDK.PropID_TimeZone, 0, out _timeZone);

            _desc = new EDSDKLib.EDSDK.EdsPropertyDesc();
            err = EDSDKLib.EDSDK.EdsGetPropertyDesc(_camera, EDSDKLib.EDSDK.PropID_TimeZone, out _desc);

            this.comboBox1.Items.Clear();

            for (int i = 0; i < _desc.NumElements; i++)
            {
                string outString;
                bool isGet = map.TryGetValue((uint)_desc.PropDesc[i] >> 16, out outString);
                if (isGet && !outString.Equals("unknown"))
                {
                    // Create list of combo box
                    comboBox1.Items.Add(outString);
                    if (_timeZone == _desc.PropDesc[i])
                    {
                        // Select item of combo box
                        comboBox1.SelectedIndex = i;
                        _timeZone = (uint)_desc.PropDesc[i];
                        _timeZonePrev = _timeZone;
                    }
                }
            }

            // Daylight Saving Time
            uint summerTimeSetting;
            err = EDSDKLib.EDSDK.EdsGetPropertyData(_camera, EDSDKLib.EDSDK.PropID_SummerTimeSetting, 0, out summerTimeSetting);
            if (summerTimeSetting == 0x01)
            {
                this.checkBox1.Checked = true;
            }
            _summerTimeSetting = this.checkBox1.Checked;
            _summerTimeSettingPrev = _summerTimeSetting;

            // Time difference consideration
            DateTime dateTime = EdsTime2DateTime(utcTime);
            short timeDiff = (short)(_timeZone & 0x0000ffff);
            TimeSpan timeSpan = new TimeSpan(0, Convert.ToInt32(this.checkBox1.Checked), timeDiff, 0);
            dateTime = dateTime.Add(timeSpan);
            utcTime = DateTime2EdsTime(dateTime);

            _localTime = EdsTime2StrTime(utcTime);
            _localTimePrev = _localTime;
            this.textBox1.Text = _localTime;
        }

        private void button1_Click(object sender, EventArgs e)
        {
            // Zone Setting
            var selectedItem = comboBox1.SelectedIndex;
            uint timeZone = (uint)_desc.PropDesc[selectedItem];
            if (_timeZone != timeZone)
            {
                uint err = EDSDKLib.EDSDK.EdsSetPropertyData(_camera, EDSDKLib.EDSDK.PropID_TimeZone, 0, sizeof(uint), timeZone);
            }
            _timeZone = timeZone;

            // Date / Time : (ex : 2019/09/12 09:11)
            string localTime = this.textBox1.Text;

            if (_localTime != localTime)
            {
                DateTime dateTime;
                if (tryParseExact(out dateTime))
                {
                    // Time difference consideration
                    short timeDiff = (short)(_timeZone & 0x0000ffff);
                    TimeSpan timeSpan = new TimeSpan(0, Convert.ToInt32(this.checkBox1.Checked), timeDiff, 0);
                    dateTime = dateTime.Subtract(timeSpan);
                    EDSDKLib.EDSDK.EdsTime edsDateTime = DateTime2EdsTime(dateTime);
                    uint err = EDSDKLib.EDSDK.EdsSetPropertyData(_camera, EDSDKLib.EDSDK.PropID_UTCTime, 0, Marshal.SizeOf(typeof(EDSDKLib.EDSDK.EdsTime)), edsDateTime);
                }
                else
                {
                    MessageBox.Show("Enter in the \"yyyy/MM/DD HH:mm\" format.");
                    this.DialogResult = DialogResult.None;
                }
            }

            // Daylight Saving Time
            if (_summerTimeSetting != this.checkBox1.Checked)
            {
                uint err = EDSDKLib.EDSDK.EdsSetPropertyData(_camera, EDSDKLib.EDSDK.PropID_SummerTimeSetting, 0, sizeof(uint), Convert.ToUInt32(this.checkBox1.Checked));
            }
        }

        private void textBox1_Leave(object sender, EventArgs e)
        {
            // Perform format check. If an error occurs, display a message and return to the original date and time.
            string utcTime = this.textBox1.Text;

            if (_localTimePrev != utcTime)
            {
                DateTime dateTime;
                if (!tryParseExact(out dateTime))
                {
                    MessageBox.Show("Enter in the \"yyyy/MM/DD HH:mm\" format.");
                    this.textBox1.Text = _localTimePrev;
                }
                else
                {
                    if (!IsRange(dateTime.Year, 2019, 2050))
                    {
                        MessageBox.Show("Year must be between 2019 and 2050");
                        this.textBox1.Text = _localTimePrev;
                    }
                    _localTimePrev = this.textBox1.Text;
                }
            }
        }

        private void comboBox1_SelectionChangeCommitted(object sender, EventArgs e)
        {
            // Update the date and time considering the time zone
            var selectedItem = comboBox1.SelectedIndex;
            uint timeZone = (uint)_desc.PropDesc[selectedItem];
            if (_timeZonePrev != timeZone)
            {
                DateTime dateTime;
                if (tryParseExact(out dateTime))
                {
                    // Old Zone -> UTC
                    short timeDiff = (short)(_timeZonePrev & 0x0000ffff);
                    TimeSpan timeSpan = new TimeSpan(0, 0, timeDiff, 0);
                    dateTime = dateTime.Subtract(timeSpan);

                    // UTC -> New Zone
                    timeDiff = (short)(timeZone & 0x0000ffff);
                    timeSpan = new TimeSpan(0, 0, timeDiff, 0);
                    dateTime = dateTime.Add(timeSpan);

                    this.textBox1.Text = EdsTime2StrTime(DateTime2EdsTime(dateTime));
                }
            }
            _timeZonePrev = timeZone;
        }

        private void checkBox1_CheckedChanged(object sender, EventArgs e)
        {
            // Update the date and time with daylight saving time in mind
            if (_summerTimeSettingPrev != this.checkBox1.Checked)
            {
                DateTime dateTime;
                if (tryParseExact(out dateTime))
                {
                    TimeSpan timeSpan = new TimeSpan(0, 1, 0, 0);
                    if (!this.checkBox1.Checked)
                    {
                        timeSpan = new TimeSpan(0, -1, 0, 0);
                    }
                    dateTime = dateTime.Add(timeSpan);
                    this.textBox1.Text = EdsTime2StrTime(DateTime2EdsTime(dateTime));
                }
            }
            _summerTimeSettingPrev = this.checkBox1.Checked;
        }

        private DateTime EdsTime2DateTime(EDSDKLib.EDSDK.EdsTime edsTime)
        {
            DateTime dateTime = new DateTime(edsTime.Year, edsTime.Month, edsTime.Day, edsTime.Hour, edsTime.Minute, edsTime.Second, edsTime.Milliseconds);
            return dateTime;
        }

        private EDSDKLib.EDSDK.EdsTime DateTime2EdsTime(DateTime dateTime)
        {
            EDSDKLib.EDSDK.EdsTime edsTime;
            edsTime.Year = dateTime.Year;
            edsTime.Month = dateTime.Month;
            edsTime.Day = dateTime.Day;
            edsTime.Hour = dateTime.Hour;
            edsTime.Minute = dateTime.Minute;
            edsTime.Second = dateTime.Second;
            edsTime.Milliseconds = dateTime.Millisecond;
            return edsTime;
        }

        private string EdsTime2StrTime(EDSDKLib.EDSDK.EdsTime edsTime)
        {
            string strTime = (edsTime.Year).ToString("D4") + "/" + edsTime.Month.ToString("D2") + "/" + edsTime.Day.ToString("D2") + " " + edsTime.Hour.ToString("D2") + ":" + edsTime.Minute.ToString("D2");
            return strTime;
        }
        private bool IsRange(int a, int from, int to)
        {
            return (from <= a && a <= to);
        }

        private bool tryParseExact(out DateTime dataTime)
        {
            string utcTime = this.textBox1.Text;
            string format = "yyyy/MM/dd HH:mm";
            var culture = CultureInfo.InvariantCulture;
            DateTimeStyles dts = DateTimeStyles.AssumeUniversal | DateTimeStyles.AdjustToUniversal;

            return DateTime.TryParseExact(utcTime, format, culture, dts, out dataTime);
        }
    }
}
