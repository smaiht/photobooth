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
    class ActionButton : System.Windows.Forms.Button
    {

        public ActionEvent.Command Command { get; set; }

        private ActionSource _actionSource;

        public void SetActionSource(ref ActionSource actionSource) { _actionSource = actionSource; }

        protected override void OnClick(EventArgs e)
        {
            _actionSource.FireEvent(this.Command, IntPtr.Zero);

            base.OnClick(e);
        }

    }
}
