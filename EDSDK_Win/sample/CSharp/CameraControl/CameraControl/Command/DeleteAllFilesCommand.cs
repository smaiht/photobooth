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

namespace CameraControl
{
    class DeleteAllFilesCommand : Command
    {
        public DeleteAllFilesCommand(ref CameraModel model, ref IntPtr volume) : base(ref model) { _volume = volume; }

        private static FileCounterCommand.FileNumber _fileNumber;
        private static int _currentFileNum = 0;
        private static int _fileCount = 0;
        private static List<IntPtr> _imageItems = new List<IntPtr>();
        private static string _targetFolderName;  // Folder to delete.


        private CameraEvent _event;
        private IntPtr _volume;
        public override bool Execute()
        {
            uint err = EDSDKLib.EDSDK.EDS_ERR_OK;
            IntPtr camera = _model.Camera;
            FileCounterCommand fileCounter = new FileCounterCommand(ref _model, ref _volume);
            _targetFolderName = "DCIM";

            while (true)
            {
                IntPtr directoryItem = IntPtr.Zero;

                // Prepare delete
                if (_currentFileNum == 0)
                {
                    int directoryCount = 0;

                    err = fileCounter.CountDirectory(camera, ref directoryItem, ref _targetFolderName, out directoryCount);

                    if (directoryItem == IntPtr.Zero)
                    {
                        break;
                    }

                    _fileNumber = new FileCounterCommand.FileNumber(directoryCount);
                    _fileNumber.DirItem = directoryItem;

                    err = fileCounter.CountImages(camera, ref directoryItem, ref directoryCount, ref _fileCount, ref _fileNumber, ref _imageItems);
                    if (err != EDSDKLib.EDSDK.EDS_ERR_OK)
                    {
                        return false;
                    }

                }

                // Show progress.
                _event = new CameraEvent(CameraEvent.Type.DELETE_START, (IntPtr)_fileCount);
                _model.NotifyObservers(_event);

                // Delete file.
                err = DeleteFileByDirectory(camera);
                if (err == EDSDKLib.EDSDK.EDS_ERR_OPERATION_CANCELLED)
                {
                    return true;
                }
                else if (err != EDSDKLib.EDSDK.EDS_ERR_OK)
                {
                    return false;
                }

                // Change target folder.
                fileCounter.ChangeTargetFolderName(ref _targetFolderName);

            }
            // Finish download files
            _event = new CameraEvent(CameraEvent.Type.DELETE_COMPLETE, camera);
            _model.NotifyObservers(_event);

            return true;
        }

        private uint DeleteFileByDirectory(IntPtr camera)
        {
            int index = 0;

            for (index = 0; index < _imageItems.Count; ++index)
            {
                uint err = EDSDKLib.EDSDK.EdsDeleteDirectoryItem(_imageItems[index]);
                if (err != EDSDKLib.EDSDK.EDS_ERR_OK)
                {
                    return err;
                }
                EDSDKLib.EDSDK.EdsRelease(_imageItems[index]);

                _currentFileNum += 1;
                if (_model._ExecuteStatus == CameraModel.Status.CANCELING)
                {
                    _event = new CameraEvent(CameraEvent.Type.DELETE_COMPLETE, (IntPtr)index);
                    _model.NotifyObservers(_event);
                    _currentFileNum = 0;
                    // Stop always.
                    _imageItems.Clear();
                    return EDSDKLib.EDSDK.EDS_ERR_OPERATION_CANCELLED;
                }
                else
                {
                    _event = new CameraEvent(CameraEvent.Type.PROGRESS_REPORT, (IntPtr)_currentFileNum);
                    _model.NotifyObservers(_event);
                }

            }
            // Finish delete files.
            _currentFileNum = 0;
            _imageItems.Clear();
            return EDSDKLib.EDSDK.EDS_ERR_OK;
        }
    }
}
