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
    class MovieQualityComboBox : PropertyComboBox, IObserver
    {
        private ActionSource _actionSource;

        private EDSDKLib.EDSDK.EdsPropertyDesc _desc;

        public void SetActionSource(ref ActionSource actionSource) { _actionSource = actionSource; }

        public MovieQualityComboBox()
        {
            map.Add(0x00000000, "");
            map.Add(0x00000200, "1920x1080_2398");
            map.Add(0x00000210, "1920x1080_2398_intra_standard");
            map.Add(0x00000230, "1920x1080_2398_ipb_standard");
            map.Add(0x00000300, "1920x1080_2400");
            map.Add(0x00000310, "1920x1080_2400_intra_standard");
            map.Add(0x00000330, "1920x1080_2400_ipb_standard");
            map.Add(0x00000400, "1920x1080_2500");
            map.Add(0x00000410, "1920x1080_2500_intra_standard");
            map.Add(0x00000430, "1920x1080_2500_ipb_standard");
            map.Add(0x00000500, "1920x1080_2997");
            map.Add(0x00000510, "1920x1080_2997_intra_standard");
            map.Add(0x00000530, "1920x1080_2997_ipb_standard");
            map.Add(0x00000610, "1920x1080_5000_intra_standard");
            map.Add(0x00000630, "1920x1080_5000_ipb_standard");
            map.Add(0x00000710, "1920x1080_5994_intra_standard");
            map.Add(0x00000730, "1920x1080_5994_ipb_standard");

            map.Add(0x00001210, "1920x1080_2398_intra_standard");
            map.Add(0x00001230, "1920x1080_2398_ipb_standard");
            map.Add(0x00001231, "1920x1080_2398_ipb_light");
            map.Add(0x00001310, "1920x1080_2400_intra_standard");
            map.Add(0x00001330, "1920x1080_2400_ipb_standard");
            map.Add(0x00001331, "1920x1080_2400_ipb_light");
            map.Add(0x00001410, "1920x1080_2500_intra_standard");
            map.Add(0x00001430, "1920x1080_2500_ipb_standard");
            map.Add(0x00001431, "1920x1080_2500_ipb_light");
            map.Add(0x00001510, "1920x1080_2997_intra_standard");
            map.Add(0x00001530, "1920x1080_2997_ipb_standard");
            map.Add(0x00001531, "1920x1080_2997_ipb_light");
            map.Add(0x00001610, "1920x1080_5000_intra_standard");
            map.Add(0x00001630, "1920x1080_5000_ipb_standard");
            map.Add(0x00001631, "1920x1080_5000_ipb_light");
            map.Add(0x00001710, "1920x1080_5994_intra_standard");
            map.Add(0x00001730, "1920x1080_5994_ipb_standard");
            map.Add(0x00001731, "1920x1080_5994_ipb_light");
            map.Add(0x00001810, "1920x1080_10000_intra_standard");
            map.Add(0x00001830, "1920x1080_10000_ipb_standard");
            map.Add(0x00001831, "1920x1080_10000_ipb_light");
            map.Add(0x00001910, "1920x1080_11988_intra_standard");
            map.Add(0x00001930, "1920x1080_11988_ipb_standard");
            map.Add(0x00001931, "1920x1080_11988_ipb_light");
            map.Add(0x00001a30, "1920x1080_15000_ipb_standard");
            map.Add(0x00001a31, "1920x1080_15000_ipb_light");
            map.Add(0x00001b30, "1920x1080_17982_ipb_standard");
            map.Add(0x00001b31, "1920x1080_17982_ipb_light");
            map.Add(0x00001c30, "1920x1080_20000_lgop_standard");
            map.Add(0x00001d10, "1920x1080_23980_intra_standard");
            map.Add(0x00001d30, "1920x1080_23980_lgop_standard");

            map.Add(0x00010600, "1280x720_5000");
            map.Add(0x00010700, "1280x720_5994");
            map.Add(0x00010810, "1280x720_1000_intra_standard");
            map.Add(0x00010910, "1280x720_1199_intra_standard");
            map.Add(0x00011430, "1280x720_2500_ipb_standard");
            map.Add(0x00011431, "1280x720_5000_ipb_standard");
            map.Add(0x00011530, "1280x720_2997_ipb_standard");
            map.Add(0x00011531, "1280x720_2997_ipb_light");
            map.Add(0x00011610, "1280x720_5000_intra_standard");
            map.Add(0x00011630, "1280x720_5000_ipb_standard");
            map.Add(0x00011710, "1280x720_5994_intra_standard");
            map.Add(0x00011730, "1280x720_5994_ipb_standard");
            map.Add(0x00011810, "1280x720_10000_intra_standard");
            map.Add(0x00011830, "1280x720_10000_ipb_standard");
            map.Add(0x00011910, "1280x720_11988_intra_standard");
            map.Add(0x00011930, "1280x720_11988_ipb_standard");
            map.Add(0x00020400, "640x480_2500");
            map.Add(0x00020500, "640x480_2397");

            map.Add(0x00030240, "4096x2160_2398_motion_jpg");
            map.Add(0x00030340, "4096x2160_2400_motion_jpg");
            map.Add(0x00030440, "4096x2160_2500_motion_jpg");
            map.Add(0x00030540, "4096x2160_2997_motion_jpg");

            map.Add(0x00031210, "4096x2160_2398_intra_standard");
            map.Add(0x00031211, "4096x2160_2398_intra_light");
            map.Add(0x00031212, "4096x2160_2398_intra_high_quality");
            map.Add(0x00031230, "4096x2160_2398_ipb_standard");
            map.Add(0x00031231, "4096x2160_2398_ipb_light");
            map.Add(0x00031310, "4096x2160_2400_intra_standard"); 
            map.Add(0x00031311, "4096x2160_2400_intra_light");
            map.Add(0x00031312, "4096x2160_2400_intra_high_quality");
            map.Add(0x00031330, "4096x2160_2400_ipb_standard");
            map.Add(0x00031331, "4096x2160_2400_ipb_light");
            map.Add(0x00031410, "4096x2160_2500_intra_standard");
            map.Add(0x00031430, "4096x2160_2500_ipb_standard");
            map.Add(0x00031431, "4096x2160_2500_ipb_light");
            map.Add(0x00031510, "4096x2160_2997_intra_standard");
            map.Add(0x00031511, "4096x2160_2997_intra_light");
            map.Add(0x00031512, "4096x2160_2997_intra_high_quality");
            map.Add(0x00031530, "4096x2160_2997_ipb_standard");
            map.Add(0x00031531, "4096x2160_2997_ipb_light");
            map.Add(0x00031610, "4096x2160_5000_intra_standard");
            map.Add(0x00031630, "4096x2160_5000_ipb_standard");
            map.Add(0x00031631, "4096x2160_5000_ipb_light");
            map.Add(0x00031710, "4096x2160_5994_intra_standard");
            map.Add(0x00031711, "4096x2160_5994_intra_light");
            map.Add(0x00031712, "4096x2160_5994_intra_high_quality");
            map.Add(0x00031730, "4096x2160_5994_ipb_standard");
            map.Add(0x00031731, "4096x2160_5994_ipb_light");
            map.Add(0x00031810, "4096x2160_10000_intra_standard");
            map.Add(0x00031830, "4096x2160_10000_lgop_standard");
            map.Add(0x00031910, "4096x2160_11988_intra_standard");
            map.Add(0x00031911, "4096x2160_11988_intra_light");
            map.Add(0x00031930, "4096x2160_11988_lgop_standard");


            map.Add(0x00051210, "3840x2160_2398_intra_standard");
            map.Add(0x00051211, "3840x2160_2398_intra_light");
            map.Add(0x00051212, "3840x2160_2398_intra_high_qualityg");
            map.Add(0x00051230, "3840x2160_2398_ipb_standard");
            map.Add(0x00051231, "3840x2160_2398_ipb_light");
            map.Add(0x00051310, "3840x2160_2400_intra_standard");
            map.Add(0x00051330, "3840x2160_2400_ipb_standard");
            map.Add(0x00051331, "3840x2160_2400_ipb_light");
            map.Add(0x00051410, "3840x2160_2500_intra_standard");
            map.Add(0x00051430, "3840x2160_2500_ipb_standard");
            map.Add(0x00051431, "3840x2160_2500_ipb_light");
            map.Add(0x00051510, "3840x2160_2997_intra_standard");
            map.Add(0x00051511, "3840x2160_2997_intra_light");
            map.Add(0x00051512, "3840x2160_2997_intra_high_quality");
            map.Add(0x00051530, "3840x2160_2997_ipb_standard");
            map.Add(0x00051531, "3840x2160_2997_ipb_light");
            map.Add(0x00051610, "3840x2160_5000_intra_standard");
            map.Add(0x00051630, "3840x2160_5000_ipb_standard");
            map.Add(0x00051631, "3840x2160_5000_ipb_light");
            map.Add(0x00051710, "3840x2160_5994_intra_standard");
            map.Add(0x00051711, "3840x2160_5994_intra_light");
            map.Add(0x00051712, "3840x2160_5994_intra_high_quality");
            map.Add(0x00051730, "3840x2160_5994_ipb_standard");
            map.Add(0x00051731, "3840x2160_5994_ipb_light");
            map.Add(0x00051810, "3840x2160_10000_intra_standard");
            map.Add(0x00051830, "3840x2160_10000_lgop_standard");
            map.Add(0x00051910, "3840x2160_11988_intra_standard");
            map.Add(0x00051911, "3840x2160_11988_intra_light");
            map.Add(0x00051930, "3840x2160_11988_lgop_standard");

            map.Add(0x00071210, "2048x1080_2398_intra_standard");
            map.Add(0x00071230, "2048x1080_2398_lgop_standard");
            map.Add(0x00071310, "2048x1080_2400_intra_standard");
            map.Add(0x00071330, "2048x1080_2400_lgop_standard");
            map.Add(0x00071410, "2048x1080_2500_intra_standard");
            map.Add(0x00071430, "2048x1080_2500_lgop_standard");
            map.Add(0x00071510, "2048x1080_2997_intra_standard");
            map.Add(0x00071530, "2048x1080_2997_lgop_standard");
            map.Add(0x00071610, "2048x1080_5000_intra_standard");
            map.Add(0x00071630, "2048x1080_5000_lgop_standard");
            map.Add(0x00071710, "2048x1080_5994_intra_standard");
            map.Add(0x00071730, "2048x1080_5994_lgop_standard");
            map.Add(0x00071810, "2048x1080_10000_intra_standard");
            map.Add(0x00071830, "2048x1080_10000_lgop_standard");
            map.Add(0x00071910, "2048x1080_11988_intra_standard");
            map.Add(0x00071930, "2048x1080_11988_lgop_standard");
            map.Add(0x00071c10, "2048x1080_20000_intra_standard");
            map.Add(0x00071c30, "2048x1080_20000_lgop_standard");
            map.Add(0x00071d10, "2048x1080_23980_intra_standard");
            map.Add(0x00071d30, "2048x1080_23980_lgop_standard");

            map.Add(0x00081210, "8192x4320_2398_intra_standard");
            map.Add(0x00081211, "8192x4320_2398_intra_light");
            map.Add(0x00081212, "8192x4320_2398_intra_high_quality");
            map.Add(0x00081230, "8192x4320_2398_ipb_standard");
            map.Add(0x00081231, "8192x4320_2398_ipb_light");
            map.Add(0x00081310, "8192x4320_2400_intra_standard");
            map.Add(0x00081311, "8192x4320_2400_intra_light");
            map.Add(0x00081312, "8192x4320_2400_intra_high_quality");

            map.Add(0x00081330, "8192x4320_2400_ipb_standard");
            map.Add(0x00081331, "8192x4320_2400_ipb_light");
            map.Add(0x00081410, "8192x4320_2500_intra_standard");
            map.Add(0x00081430, "8192x4320_2500_ipb_standard");
            map.Add(0x00081431, "8192x4320_2500_ipb_light");
            map.Add(0x00081510, "8192x4320_2997_intra_standard");
            map.Add(0x00081511, "8192x4320_2997_intra_light");
            map.Add(0x00081512, "8192x4320_2997_intra_high_quality");
            map.Add(0x00081530, "8192x4320_2997_ipb_standard");
            map.Add(0x00081531, "8192x4320_2997_ipb_light");
            map.Add(0x00091210, "7680x4320_2398_intra_standard");
            map.Add(0x00091211, "7680x4320_2398_intra_light");
            map.Add(0x00091212, "7680x4320_2398_intra_high_quality");
            map.Add(0x00091230, "7680x4320_2398_ipb_standard");
            map.Add(0x00091231, "7680x4320_2398_ipb_light");
            map.Add(0x00091330, "7680x4320_2400_ipb_standard");
            map.Add(0x00091331, "7680x4320_2400_ipb_light");
            map.Add(0x00091410, "7680x4320_2500_intra_standard");
            map.Add(0x00091430, "7680x4320_2500_ipb_standard");
            map.Add(0x00091431, "7680x4320_2500_ipb_light");
            map.Add(0x00091510, "7680x4320_2997_intra_standard");
            map.Add(0x00091511, "7680x4320_2997_intra_light");
            map.Add(0x00091512, "7680x4320_2997_intra_high_quality");
            map.Add(0x00091530, "7680x4320_2997_ipb_standard");
            map.Add(0x00091531, "7680x4320_2997_ipb_light");

            map.Add(0x000a3270, "2398_raw_standard");
            map.Add(0x000a3271, "2398_raw_light");
            map.Add(0x000a3370, "2400_raw_standard");
            map.Add(0x000a3371, "2400_raw_light");
            map.Add(0x000a3470, "2500_raw_standard");
            map.Add(0x000a3471, "2500_raw_light");
            map.Add(0x000a3570, "2997_raw_standard");
            map.Add(0x000a3571, "2997_raw_light");
            map.Add(0x000a3670, "5000_raw_standard");
            map.Add(0x000a3770, "5994_raw_standard");
            map.Add(0x000a3771, "5994_raw_standard");
            map.Add(0x000b3270, "2398_sraw_standard");
            map.Add(0x000b3271, "2398_sraw_light");
            map.Add(0x000b3370, "2400_sraw_standard");
            map.Add(0x000b3371, "2400_sraw_light");
            map.Add(0x000b3570, "2997_sraw_standard");
            map.Add(0x000b3571, "2997_sraw_light");
            map.Add(0x000b3770, "5994_sraw_standard");
            map.Add(0x000b3771, "5994_sraw_light");

            map.Add(0x08001210, "1920x1080_2398_intra_standard_crop");
            map.Add(0x08001230, "1920x1080_2398_ipb_standard_crop(LGOP)");
            map.Add(0x08001231, "1920x1080_2398_ipb_light_crop");
            map.Add(0x08001410, "1920x1080_2500_intra_standard_crop");
            map.Add(0x08001430, "1920x1080_2500_ipb_standard_crop(LGOP)");
            map.Add(0x08001431, "1920x1080_2500_ipb_light_crop");
            map.Add(0x08001510, "1920x1080_2997_intra_standard_crop");
            map.Add(0x08001530, "1920x1080_2997_ipb_standard_crop(LGOP)");
            map.Add(0x08001531, "1920x1080_2997_ipb_light_crop");
            map.Add(0x08001610, "1920x1080_5000_intra_standard_crop");
            map.Add(0x08001630, "1920x1080_5000_ipb_standard_crop(LGOP)");
            map.Add(0x08001631, "1920x1080_5000_ipb_light_crop");
            map.Add(0x08001710, "1920x1080_5994_intra_standard_crop");
            map.Add(0x08001730, "1920x1080_5994_ipb_standard_crop(LGOP)");
            map.Add(0x08001731, "1920x1080_5994_ipb_light_crop");
            map.Add(0x08001810, "1920x1080_10000_intra_standard_crop");
            map.Add(0x08001830, "1920x1080_10000_ipb_standard_crop(LGOP)");
            map.Add(0x08001910, "1920x1080_11988_intra_standard_crop");
            map.Add(0x08001930, "1920x1080_11990_ipb_standard_crop(LGOP)");

            map.Add(0x08031210, "4096x2160_2398_intra_standard_crop");
            map.Add(0x08031211, "4096x2160_2398_intra_light");
            map.Add(0x08031212, "4096x2160_2398_intra_high_quality");
            map.Add(0x08031230, "4096x2160_2398_ipb_standard_crop(LGOP)");
            map.Add(0x08031231, "4096x2160_2398_ipb_light_crop");
            map.Add(0x08031310, "4096x2160_2400_intra_standard_crop");
            map.Add(0x08031311, "4096x2160_2400_intra_light");
            map.Add(0x08031312, "4096x2160_2400_intra_high_quality");
            map.Add(0x08031330, "4096x2160_2400_ipb_standard_crop(LGOP)");
            map.Add(0x08031331, "4096x2160_2400_ipb_light_crop");
            map.Add(0x08031410, "4096x2160_2500_intra_standard_crop");
            map.Add(0x08031411, "4096x2160_2500_intra_light");
            map.Add(0x08031412, "4096x2160_2500_intra_high_quality");
            map.Add(0x08031430, "4096x2160_2500_ipb_standard_crop(LGOP)");
            map.Add(0x08031431, "4096x2160_2500_ipb_light_crop");
            map.Add(0x08031510, "4096x2160_2997_intra_standard_crop");
            map.Add(0x08031511, "4096x2160_2997_intra_light");
            map.Add(0x08031512, "4096x2160_2997_intra_high_quality");
            map.Add(0x08031530, "4096x2160_2997_ipb_standard_crop(LGOP)");
            map.Add(0x08031531, "4096x2160_2997_ipb_light_crop");
            map.Add(0x08031610, "4096x2160_5000_intra_standard_crop");
            map.Add(0x08031611, "4096x2160_5994_intra_light");
            map.Add(0x08031612, "4096x2160_5000_intra_high_quality");
            map.Add(0x08031630, "4096x2160_5000_ipb_standard_crop(LGOP)");
            map.Add(0x08031631, "4096x2160_5000_ipb_light_crop");
            map.Add(0x08031710, "4096x2160_5994_intra_standard_crop");
            map.Add(0x08031711, "4096x2160_5994_intra_light");
            map.Add(0x08031712, "4096x2160_5994_intra_high_quality");
            map.Add(0x08031730, "4096x2160_5994_ipb_standard_crop(LGOP)");
            map.Add(0x08031731, "4096x2160_5994_ipb_light_crop");
            map.Add(0x08031810, "4096x2160_10000_intra");
            map.Add(0x08031811, "4096x2160_10000_intra_light");
            map.Add(0x08031830, "4096x2160_10000_ipb_standard_crop(LGOP)");
            map.Add(0x08031910, "4096x2160_11990_intra");
            map.Add(0x08031911, "4096x2160_11990_intra_light");
            map.Add(0x08031930, "4096x2160_11990_ipb_standard_crop(LGOP)");

            map.Add(0x08051210, "3840x2160_2398_intra_standard_crop");
            map.Add(0x08051211, "3840x2160_2398_intra_light");
            map.Add(0x08051212, "3840x2160_2398_intra_high_quality");
            map.Add(0x08051230, "3840x2160_2398_ipb_standard_crop(LGOP)");
            map.Add(0x08051231, "3840x2160_2398_ipb_light_crop");
            map.Add(0x08051410, "3840x2160_2500_intra_standard_crop");
            map.Add(0x08051411, "3840x2160_2500_intra_light");
            map.Add(0x08051412, "3840x2160_2500_intra_high_quality");
            map.Add(0x08051430, "3840x2160_2500_ipb_standard_crop(LGOP)");
            map.Add(0x08051431, "3840x2160_2500_ipb_light_crop");
            map.Add(0x08051510, "3840x2160_2997_intra_standard_crop");
            map.Add(0x08051511, "3840x2160_2997_intra_light");
            map.Add(0x08051512, "3840x2160_2997_intra_high_quality");
            map.Add(0x08051530, "3840x2160_2997_ipb_standard_crop(LGOP)");
            map.Add(0x08051531, "3840x2160_2997_ipb_light_crop");
            map.Add(0x08051610, "3840x2160_5000_intra_standard_crop");
            map.Add(0x08051611, "3840x2160_5000_intra_light");
            map.Add(0x08051612, "3840x2160_5000_high_quality");
            map.Add(0x08051630, "3840x2160_5000_ipb_standard_crop(LGOP)");
            map.Add(0x08051631, "3840x2160_5000_ipb_light_crop");
            map.Add(0x08051710, "3840x2160_5994_intra_standard_crop");
            map.Add(0x08051711, "3840x2160_5994_intra_light");
            map.Add(0x08051712, "3840x2160_5994_intra_high_quality");
            map.Add(0x08051730, "3840x2160_5994_ipb_standard_crop(LGOP)");
            map.Add(0x08051731, "3840x2160_5994_ipb_light_crop");
            map.Add(0x08051810, "3840x2160_10000_intra");
            map.Add(0x08051811, "3840x2160_10000_intra_light");
            map.Add(0x08051830, "3840x2160_10000_ipb_standard_crop(LGOP)");
            map.Add(0x08051910, "3840x2160_11990_intra");
            map.Add(0x08051911, "3840x2160_11990_intra_light");
            map.Add(0x08051930, "3840x2160_11990_ipb_standard_crop(LGOP)");

            map.Add(0x08071210, "2048x1080_2398_intra");
            map.Add(0x08071230, "2048x1080_2398_ipb_standard_crop(LGOP)");
            map.Add(0x08071310, "2048x1080_2400_intra");
            map.Add(0x08071330, "2048x1080_2400_ipb_standard_crop(LGOP)");
            map.Add(0x08071410, "2048x1080_2500_intra");
            map.Add(0x08071430, "2048x1080_2500_ipb_standard_crop(LGOP)");
            map.Add(0x08071510, "2048x1080_2997_intra");
            map.Add(0x08071530, "2048x1080_2997_ipb_standard_crop(LGOP)");
            map.Add(0x08071610, "2048x1080_5000_intra");
            map.Add(0x08071630, "2048x1080_5000_ipb_standard_crop(LGOP)");
            map.Add(0x08071710, "2048x1080_5994_intra");
            map.Add(0x08071730, "2048x1080_5994_ipb_standard_crop(LGOP)");
            map.Add(0x08071810, "2048x1080_10000_intra");
            map.Add(0x08071830, "2048x1080_10000_ipb_standard_crop(LGOP)");
            map.Add(0x08071910, "2048x1080_11990_intra");
            map.Add(0x08071930, "2048x1080_11990_ipb_standard_crop(LGOP)");

            map.Add(0x10001210, "1920x1080_fine_2398_intra_standard");
            map.Add(0x10001230, "1920x1080_fine_2398_lgop_standard");
            map.Add(0x10001410, "1920x1080_fine_2500_intra_standard");
            map.Add(0x10001430, "1920x1080_fine_2500_lgop_standard");
            map.Add(0x10001510, "1920x1080_fine_2997_intra_standard");
            map.Add(0x10001530, "1920x1080_fine_2997_lgop_standard");
            map.Add(0x10001610, "1920x1080_fine_5000_intra_standard");
            map.Add(0x10001630, "1920x1080_fine_5000_lgop_standard");
            map.Add(0x10001710, "1920x1080_fine_5994_intra_standard");
            map.Add(0x10001730, "1920x1080_fine_5994_lgop_standard");
            map.Add(0x10031210, "4096x2160_fine_2398_intra_standard");
            map.Add(0x10031211, "4096x2160_fine_2398_intra_light");
            map.Add(0x10031212, "4096x2160_fine_2398_intra_high_quality");
            map.Add(0x10031230, "4096x2160_fine_2398_lgop_standard");
            map.Add(0x10031310, "4096x2160_fine_2400_intra_standard");
            map.Add(0x10031311, "4096x2160_fine_2400_intra_light");
            map.Add(0x10031312, "4096x2160_fine_2400_intra_high_quality");
            map.Add(0x10031330, "4096x2160_fine_2400_lgop_standard");
            map.Add(0x10031410, "4096x2160_fine_2500_intra_standard");
            map.Add(0x10031430, "4096x2160_fine_2500_lgop_standard");
            map.Add(0x10031510, "4096x2160_fine_2997_intra_standard");
            map.Add(0x10031511, "4096x2160_fine_2997_intra_light");
            map.Add(0x10031512, "4096x2160_fine_2997_intra_high_quality");
            map.Add(0x10031530, "4096x2160_fine_2997_lgop_standard");
            map.Add(0x10031610, "4096x2160_fine_5000_intra_standard");
            map.Add(0x10031630, "4096x2160_fine_5000_lgop_standard");
            map.Add(0x10031710, "4096x2160_fine_5994_intra_standard");
            map.Add(0x10031730, "4096x2160_fine_5994_lgop_standard");
            map.Add(0x10051210, "3840x2160_fine_2398_intra_standard");
            map.Add(0x10051211, "3840x2160_fine_2398_intra_light");
            map.Add(0x10051212, "3840x2160_fine_2398_intra_high_quality");
            map.Add(0x10051230, "3840x2160_fine_2398_ipb_standard");
            map.Add(0x10051231, "3840x2160_fine_2398_ipb_light");
            map.Add(0x10051430, "3840x2160_fine_2500_ipb_standard");
            map.Add(0x10051431, "3840x2160_fine_2500_ipb_light");
            map.Add(0x10051510, "3840x2160_fine_2997_intra_standard");
            map.Add(0x10051511, "3840x2160_fine_2997_intra_light");
            map.Add(0x10051512, "3840x2160_fine_2997_intra_high_quality");
            map.Add(0x10051530, "3840x2160_fine_2997_ipb_standard");
            map.Add(0x10051531, "3840x2160_fine_2997_ipb_light");
            map.Add(0x10051630, "3840x2160_fine_5000_ipb_standard");
            map.Add(0x10051710, "3840x2160_fine_5994_intra_standard");
            map.Add(0x10051730, "3840x2160_fine_5994_ipb_standard");
            map.Add(0x10071210, "2048x1080_fine_2398_intra_standard");
            map.Add(0x10071230, "2048x1080_fine_2398_lgop_standard");
            map.Add(0x10071310, "2048x1080_fine_2400_intra_standard");
            map.Add(0x10071330, "2048x1080_fine_2400_lgop_standard");
            map.Add(0x10071410, "2048x1080_fine_2500_intra_standard");
            map.Add(0x10071430, "2048x1080_fine_2500_lgop_standard");
            map.Add(0x10071510, "2048x1080_fine_2997_intra_standard");
            map.Add(0x10071530, "2048x1080_fine_2997_lgop_standard");
            map.Add(0x10071610, "2048x1080_fine_5000_intra_standard");
            map.Add(0x10071630, "2048x1080_fine_5000_lgop_standard");
            map.Add(0x10071710, "2048x1080_fine_5994_intra_standard");
            map.Add(0x10071730, "2048x1080_fine_5994_lgop_standard");

            map.Add(0xffffffff, "unknown");
        }

        protected override void OnSelectionChangeCommitted(EventArgs e)
        {
            if (this.SelectedItem != null)
            {
                uint key = (uint)_desc.PropDesc[this.SelectedIndex];

                _actionSource.FireEvent(ActionEvent.Command.SET_MOVIEQUALITY, (IntPtr)key);
            }
        }

        public void Update(Observable from, CameraEvent e)
        {

            CameraModel model = (CameraModel)from;
            CameraEvent.Type eventType = CameraEvent.Type.NONE;

            if ((eventType = e.GetEventType()) == CameraEvent.Type.PROPERTY_CHANGED || eventType == CameraEvent.Type.PROPERTY_DESC_CHANGED)
            {
                uint propertyID = (uint)e.GetArg();

                if (propertyID == EDSDKLib.EDSDK.PropID_MovieParam)
                {
                    uint property = model.MovieQuality;

                    //Update property
                    switch (eventType)
                    {
                        case CameraEvent.Type.PROPERTY_CHANGED:
                            this.UpdateProperty(property);
                            break;

                        case CameraEvent.Type.PROPERTY_DESC_CHANGED:
                            _desc = model.MovieQualityDesc;
                            this.UpdatePropertyDesc(ref _desc);
                            this.UpdateProperty(property);
                            break;
                    }
                }
            }
        }
    }
}
