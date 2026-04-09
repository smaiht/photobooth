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

namespace CameraControl
{
    public class CameraModel : Observable
    {
        public IntPtr Camera { get; set; }

        // Model name
        public string ModelName { get; set; }

        // Type DS
        public bool isTypeDS { get; set; }

        // Taking a picture parameter
        public uint AEMode { get; set; }
        public uint AFMode { get; set; }
        public uint DriveMode { get; set; }
        public uint WhiteBalance { get; set; }
        public uint Av { get; set; }
        public uint Tv { get; set; }
        public uint Iso { get; set; }
        public uint MeteringMode { get; set; }
        public uint ExposureCompensation { get; set; }
        public uint ImageQuality { get; set; }
        public uint AvailableShot { get; set; }
        public uint EvfMode { get; set; }
        public uint StartupEvfOutputDevice { get; set; }
        public uint EvfOutputDevice { get; set; }
        public uint EvfDepthOfFieldPreview { get; set; }
        public uint EvfAFMode { get; set; }
        public EDSDKLib.EDSDK.EdsFocusInfo FocusInfo { get; set; }
        public uint BatteryLebel { get; set; }
        public uint Zoom { get; set; }
        public EDSDKLib.EDSDK.EdsRect ZoomRect { get; set; }
        public uint FlashMode { get; set; }
        public bool canDownloadImage { get; set; }
        public bool isEvfEnable { get; set; }
        public uint TempStatus { get; set; }
        public uint RollPitch { get; set; }
        public uint MovieQuality { get; set; }
        public uint MovieHFR { get; set; }
        public uint PictureStyle { get; set; }
        public uint Aspect { get; set; }
        public EDSDKLib.EDSDK.EdsRect VisibleRect { get; set; }
        public uint FixedMovie { get; set; }
        public uint MirrorUpSetting { get; set; }
        public uint MirrorLockUpState { get; set; }
        public byte[] ClickWB { get; set; }
        public int ClickPoint { get; set; }
        public uint AutoPowerOff { get; set; }
        public EDSDKLib.EDSDK.EdsSize SizeJpegLarge { get; set; }

        public EDSDKLib.EDSDK.EdsPropertyDesc AEModeDesc { get; set; }
        public EDSDKLib.EDSDK.EdsPropertyDesc DriveModeDesc { get; set; }
        public EDSDKLib.EDSDK.EdsPropertyDesc WhiteBalanceDesc { get; set; }
        public EDSDKLib.EDSDK.EdsPropertyDesc AvDesc { get; set; }
        public EDSDKLib.EDSDK.EdsPropertyDesc TvDesc { get; set; }
        public EDSDKLib.EDSDK.EdsPropertyDesc IsoDesc { get; set; }
        public EDSDKLib.EDSDK.EdsPropertyDesc MeteringModeDesc { get; set; }
        public EDSDKLib.EDSDK.EdsPropertyDesc ExposureCompensationDesc { get; set; }
        public EDSDKLib.EDSDK.EdsPropertyDesc ImageQualityDesc { get; set; }
        public EDSDKLib.EDSDK.EdsPropertyDesc EvfAFModeDesc { get; set; }
        public EDSDKLib.EDSDK.EdsPropertyDesc ZoomDesc { get; set; }
        public EDSDKLib.EDSDK.EdsPropertyDesc FlashModeDesc { get; set; }
        public EDSDKLib.EDSDK.EdsPropertyDesc MovieQualityDesc { get; set; }
        public EDSDKLib.EDSDK.EdsPropertyDesc MovieHFRDesc { get; set; }
        public EDSDKLib.EDSDK.EdsPropertyDesc PictureStyleDesc { get; set; }
        public EDSDKLib.EDSDK.EdsPropertyDesc AspectDesc { get; set; }
        public EDSDKLib.EDSDK.EdsPropertyDesc AutoPowerOffDesc { get; set; }

        public enum Status
        {
            NONE,
            DOWNLOADING,
            DELETEING,
            CANCELING
        }
        public CameraModel.Status _ExecuteStatus;

        // Constructor
        public CameraModel(IntPtr camera)
        {
            const uint UnKnownCode = 0xffffffff;

            this.Camera = camera;
            this.AEMode = UnKnownCode;
            this.AFMode = UnKnownCode;
            this.DriveMode = UnKnownCode;
            this.WhiteBalance = UnKnownCode;
            this.Av = UnKnownCode;
            this.Tv = UnKnownCode;
            this.Iso = UnKnownCode;
            this.MeteringMode = UnKnownCode;
            this.ExposureCompensation = UnKnownCode;
            this.ImageQuality = UnKnownCode;
            this.EvfMode = UnKnownCode;
            this.EvfOutputDevice = UnKnownCode;
            this.EvfDepthOfFieldPreview = UnKnownCode;
            this.EvfAFMode = UnKnownCode;
            this.BatteryLebel = UnKnownCode;
            this.Zoom = UnKnownCode;
            this.FlashMode = UnKnownCode;
            this.AvailableShot = 0;
            this.canDownloadImage = true;
            this.TempStatus = UnKnownCode;
            this.RollPitch = 1;
            this.MovieQuality = UnKnownCode;
            this.MovieHFR = UnKnownCode;
            this.PictureStyle = UnKnownCode;
            this.Aspect = UnKnownCode;
            this.FixedMovie = UnKnownCode;
            this.MirrorUpSetting = UnKnownCode;
            this.MirrorLockUpState = UnKnownCode;
            this.AutoPowerOff = UnKnownCode;
        }

        public void SetPropertyUInt32(uint propertyID, uint value)
        {
            switch (propertyID)
            {
                case EDSDKLib.EDSDK.PropID_AEModeSelect: this.AEMode = value; break;
                case EDSDKLib.EDSDK.PropID_AFMode: this.AFMode = value; break;
                case EDSDKLib.EDSDK.PropID_DriveMode: this.DriveMode = value; break;
                case EDSDKLib.EDSDK.PropID_Tv: this.Tv = value; break;
                case EDSDKLib.EDSDK.PropID_Av: this.Av = value; break;
                case EDSDKLib.EDSDK.PropID_ISOSpeed: this.Iso = value; break;
                case EDSDKLib.EDSDK.PropID_MeteringMode: this.MeteringMode = value; break;
                case EDSDKLib.EDSDK.PropID_ExposureCompensation: this.ExposureCompensation = value; break;
                case EDSDKLib.EDSDK.PropID_ImageQuality: this.ImageQuality = value; break;
                case EDSDKLib.EDSDK.PropID_Evf_Mode: this.EvfMode = value; break;
                case EDSDKLib.EDSDK.PropID_Evf_OutputDevice: if (this.EvfOutputDevice == 0xffffffff) StartupEvfOutputDevice = value;  this.EvfOutputDevice = value; break;
                case EDSDKLib.EDSDK.PropID_Evf_DepthOfFieldPreview: this.EvfDepthOfFieldPreview = value; break;
                case EDSDKLib.EDSDK.PropID_Evf_AFMode: this.EvfAFMode = value; break;
                case EDSDKLib.EDSDK.PropID_AvailableShots: this.AvailableShot = value; break;
                case EDSDKLib.EDSDK.PropID_DC_Zoom: this.Zoom = value; break;
                case EDSDKLib.EDSDK.PropID_DC_Strobe: this.FlashMode = value; break;
                case EDSDKLib.EDSDK.PropID_TempStatus: this.TempStatus = value; break;
                case EDSDKLib.EDSDK.PropID_PictureStyle: this.PictureStyle = value; break;
                case EDSDKLib.EDSDK.PropID_MovieHFRSetting: this.MovieHFR = value; break;
                case EDSDKLib.EDSDK.PropID_Aspect: this.Aspect = value; break;
                case EDSDKLib.EDSDK.PropID_FixedMovie: this.FixedMovie = value; break;
                case EDSDKLib.EDSDK.PropID_MirrorUpSetting: this.MirrorUpSetting = value; break;
                case EDSDKLib.EDSDK.PropID_MirrorLockUpState: this.MirrorLockUpState = value; break;
                case EDSDKLib.EDSDK.PropID_AutoPowerOffSetting: this.AutoPowerOff = value; break;
            }
        }

        public void SetPropertyInt32(uint propertyID, uint value)
        {
            switch (propertyID)
            {
                case EDSDKLib.EDSDK.PropID_WhiteBalance: this.WhiteBalance = value; break;
                case EDSDKLib.EDSDK.PropID_BatteryLevel: this.BatteryLebel = value; break;
            }
        }

        //Setting of taking a picture parameter(String)
        public void SetPropertyString(uint propertyID, String str)
        {
            switch (propertyID)
            {
                case EDSDKLib.EDSDK.PropID_ProductName: this.ModelName = str; this.isTypeDS = str.Contains("EOS"); break;
            }
        }

        public void SetPropertyFocusInfo(uint propertyID, EDSDKLib.EDSDK.EdsFocusInfo info)
        {
            switch (propertyID)
            {
                case EDSDKLib.EDSDK.PropID_FocusInfo: this.FocusInfo = info; break;
            }
        }

        public void SetPropertyByteBlock(uint propertyID, byte[] data)
        {
            switch (propertyID)
            {
                case EDSDKLib.EDSDK.PropID_MovieParam: this.MovieQuality = BitConverter.ToUInt32(data, 0); break;
                case EDSDKLib.EDSDK.PropID_Evf_ClickWBCoeffs: this.ClickWB = data; break;
            }
        }

        public void SetPropertyRect(uint propertyID, EDSDKLib.EDSDK.EdsRect info)
        {
            switch (propertyID)
            {
                case EDSDKLib.EDSDK.PropID_Evf_ZoomRect: this.ZoomRect = info; break;
                case EDSDKLib.EDSDK.PropID_Evf_VisibleRect: this.VisibleRect = info; break;
            }
        }

        //Setting of value list that can set taking a picture parameter
        public void SetPropertyDesc(uint propertyID, ref EDSDKLib.EDSDK.EdsPropertyDesc desc)
        {
            switch (propertyID)
            {
                case EDSDKLib.EDSDK.PropID_AEModeSelect: this.AEModeDesc = desc; break;
                case EDSDKLib.EDSDK.PropID_DriveMode: this.DriveModeDesc = desc; break;
                case EDSDKLib.EDSDK.PropID_WhiteBalance: this.WhiteBalanceDesc = desc; break;
                case EDSDKLib.EDSDK.PropID_Tv: this.TvDesc = desc; break;
                case EDSDKLib.EDSDK.PropID_Av: this.AvDesc = desc; break;
                case EDSDKLib.EDSDK.PropID_ISOSpeed: this.IsoDesc = desc; break;
                case EDSDKLib.EDSDK.PropID_MeteringMode: this.MeteringModeDesc = desc; break;
                case EDSDKLib.EDSDK.PropID_ExposureCompensation: this.ExposureCompensationDesc = desc; break;
                case EDSDKLib.EDSDK.PropID_ImageQuality: this.ImageQualityDesc = desc; break;
                case EDSDKLib.EDSDK.PropID_Evf_AFMode: this.EvfAFModeDesc = desc; break;
                case EDSDKLib.EDSDK.PropID_DC_Zoom: this.ZoomDesc = desc; break;
                case EDSDKLib.EDSDK.PropID_DC_Strobe: this.FlashModeDesc = desc; break;
                case EDSDKLib.EDSDK.PropID_MovieParam: this.MovieQualityDesc = desc; break;
                case EDSDKLib.EDSDK.PropID_MovieHFRSetting: this.MovieHFRDesc = desc; break;
                case EDSDKLib.EDSDK.PropID_PictureStyle: this.PictureStyleDesc = desc; break;
                case EDSDKLib.EDSDK.PropID_Aspect: this.AspectDesc = desc; break;
                case EDSDKLib.EDSDK.PropID_AutoPowerOffSetting: this.AutoPowerOffDesc = desc; break;
            }
        }
        
        //Acquisition of value list that can set taking a picture parameter
        public EDSDKLib.EDSDK.EdsPropertyDesc GetPropertyDesc(uint propertyID)
        {
            EDSDKLib.EDSDK.EdsPropertyDesc desc = new EDSDKLib.EDSDK.EdsPropertyDesc { };
            switch (propertyID)
            {
                case EDSDKLib.EDSDK.PropID_AEModeSelect: desc = this.AEModeDesc; break;
                case EDSDKLib.EDSDK.PropID_DriveMode: desc = this.DriveModeDesc; break;
                case EDSDKLib.EDSDK.PropID_WhiteBalance: desc = this.WhiteBalanceDesc; break;
                case EDSDKLib.EDSDK.PropID_Tv: desc = this.TvDesc; break;
                case EDSDKLib.EDSDK.PropID_Av: desc = this.AvDesc; break;
                case EDSDKLib.EDSDK.PropID_ISOSpeed: desc = this.IsoDesc; break;
                case EDSDKLib.EDSDK.PropID_MeteringMode: desc = this.MeteringModeDesc; break;
                case EDSDKLib.EDSDK.PropID_ExposureCompensation: desc = this.ExposureCompensationDesc; break;
                case EDSDKLib.EDSDK.PropID_ImageQuality: desc = this.ImageQualityDesc; break;
                case EDSDKLib.EDSDK.PropID_Evf_AFMode: desc = this.EvfAFModeDesc; break;
                case EDSDKLib.EDSDK.PropID_DC_Zoom: desc = this.ZoomDesc; break;
                case EDSDKLib.EDSDK.PropID_DC_Strobe: desc = this.FlashModeDesc; break;
                case EDSDKLib.EDSDK.PropID_MovieParam: desc = this.MovieQualityDesc; break;
                case EDSDKLib.EDSDK.PropID_MovieHFRSetting: desc = this.MovieHFRDesc; break;
                case EDSDKLib.EDSDK.PropID_PictureStyle: desc = this.PictureStyleDesc; break;
                case EDSDKLib.EDSDK.PropID_Aspect: desc = this.AspectDesc; break;
                case EDSDKLib.EDSDK.PropID_AutoPowerOffSetting: desc = this.AutoPowerOffDesc; break;
            }
            return desc;
        }

        public EDSDKLib.EDSDK.EdsPoint GetZoomPosition()
        {
            EDSDKLib.EDSDK.EdsPoint zoomPosition;
            zoomPosition.x = this.ZoomRect.x;
            zoomPosition.y = this.ZoomRect.y;
            return zoomPosition;
        }
    }
}

