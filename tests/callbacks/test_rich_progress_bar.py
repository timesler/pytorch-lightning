# Copyright The PyTorch Lightning team.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
from unittest import mock
from unittest.mock import DEFAULT, Mock

import pytest
from torch.utils.data import DataLoader

from pytorch_lightning import Trainer
from pytorch_lightning.callbacks import ProgressBarBase, RichProgressBar
from pytorch_lightning.callbacks.progress.rich_progress import RichProgressBarTheme
from tests.helpers.boring_model import BoringModel, RandomDataset, RandomIterableDataset
from tests.helpers.runif import RunIf


@RunIf(rich=True)
def test_rich_progress_bar_callback():
    trainer = Trainer(callbacks=RichProgressBar())

    progress_bars = [c for c in trainer.callbacks if isinstance(c, ProgressBarBase)]

    assert len(progress_bars) == 1
    assert isinstance(trainer.progress_bar_callback, RichProgressBar)


@RunIf(rich=True)
def test_rich_progress_bar_refresh_rate_enabled():
    progress_bar = RichProgressBar(refresh_rate=1)
    assert progress_bar.is_enabled
    assert not progress_bar.is_disabled
    progress_bar = RichProgressBar(refresh_rate=0)
    assert not progress_bar.is_enabled
    assert progress_bar.is_disabled


@RunIf(rich=True)
@pytest.mark.parametrize("dataset", [RandomDataset(32, 64), RandomIterableDataset(32, 64)])
def test_rich_progress_bar(tmpdir, dataset):
    class TestModel(BoringModel):
        def train_dataloader(self):
            return DataLoader(dataset=dataset)

        def val_dataloader(self):
            return DataLoader(dataset=dataset)

        def test_dataloader(self):
            return DataLoader(dataset=dataset)

        def predict_dataloader(self):
            return DataLoader(dataset=dataset)

    def _initialize_trainer():
        trainer = Trainer(
            default_root_dir=tmpdir,
            num_sanity_val_steps=0,
            limit_train_batches=1,
            limit_val_batches=1,
            limit_test_batches=1,
            limit_predict_batches=1,
            max_steps=1,
            callbacks=RichProgressBar(),
        )
        return trainer

    model = TestModel()

    trainer = _initialize_trainer()
    with mock.patch("pytorch_lightning.callbacks.progress.rich_progress.Progress.update") as mocked:
        trainer.fit(model)
        # 3 for main progress bar and 1 for val progress bar
        assert mocked.call_count == 4

    trainer = _initialize_trainer()
    with mock.patch("pytorch_lightning.callbacks.progress.rich_progress.Progress.update") as mocked:
        trainer.validate(model)
        assert mocked.call_count == 1

    trainer = _initialize_trainer()
    with mock.patch("pytorch_lightning.callbacks.progress.rich_progress.Progress.update") as mocked:
        trainer.test(model)
        assert mocked.call_count == 1

    trainer = _initialize_trainer()
    with mock.patch("pytorch_lightning.callbacks.progress.rich_progress.Progress.update") as mocked:
        trainer.predict(model)
        assert mocked.call_count == 1


def test_rich_progress_bar_import_error(monkeypatch):
    import pytorch_lightning.callbacks.progress.rich_progress as imports

    monkeypatch.setattr(imports, "_RICH_AVAILABLE", False)
    with pytest.raises(ModuleNotFoundError, match="`RichProgressBar` requires `rich` >= 10.2.2."):
        RichProgressBar()


@RunIf(rich=True)
def test_rich_progress_bar_custom_theme(tmpdir):
    """Test to ensure that custom theme styles are used."""
    with mock.patch.multiple(
        "pytorch_lightning.callbacks.progress.rich_progress",
        CustomBarColumn=DEFAULT,
        BatchesProcessedColumn=DEFAULT,
        CustomTimeColumn=DEFAULT,
        ProcessingSpeedColumn=DEFAULT,
    ) as mocks:
        theme = RichProgressBarTheme()

        progress_bar = RichProgressBar(theme=theme)
        progress_bar.on_train_start(Trainer(tmpdir), BoringModel())

        assert progress_bar.theme == theme
        args, kwargs = mocks["CustomBarColumn"].call_args
        assert kwargs["complete_style"] == theme.progress_bar
        assert kwargs["finished_style"] == theme.progress_bar_finished

        args, kwargs = mocks["BatchesProcessedColumn"].call_args
        assert kwargs["style"] == theme.batch_progress

        args, kwargs = mocks["CustomTimeColumn"].call_args
        assert kwargs["style"] == theme.time

        args, kwargs = mocks["ProcessingSpeedColumn"].call_args
        assert kwargs["style"] == theme.processing_speed


@RunIf(rich=True)
def test_rich_progress_bar_keyboard_interrupt(tmpdir):
    """Test to ensure that when the user keyboard interrupts, we close the progress bar."""

    class TestModel(BoringModel):
        def on_train_start(self) -> None:
            raise KeyboardInterrupt

    model = TestModel()

    with mock.patch(
        "pytorch_lightning.callbacks.progress.rich_progress.Progress.stop", autospec=True
    ) as mock_progress_stop:
        progress_bar = RichProgressBar()
        trainer = Trainer(
            default_root_dir=tmpdir,
            fast_dev_run=True,
            callbacks=progress_bar,
        )

        trainer.fit(model)
    mock_progress_stop.assert_called_once()


@RunIf(rich=True)
def test_rich_progress_bar_configure_columns():
    from rich.progress import TextColumn

    custom_column = TextColumn("[progress.description]Testing Rich!")

    class CustomRichProgressBar(RichProgressBar):
        def configure_columns(self, trainer):
            return [custom_column]

    progress_bar = CustomRichProgressBar()

    progress_bar._init_progress(Mock())

    assert progress_bar.progress.columns[0] == custom_column
    assert len(progress_bar.progress.columns) == 2


@RunIf(rich=True)
@pytest.mark.parametrize(("leave", "reset_call_count"), ([(True, 0), (False, 5)]))
def test_rich_progress_bar_leave(tmpdir, leave, reset_call_count):
    # Calling `reset` means continuing on the same progress bar.
    model = BoringModel()

    with mock.patch(
        "pytorch_lightning.callbacks.progress.rich_progress.Progress.reset", autospec=True
    ) as mock_progress_reset:
        progress_bar = RichProgressBar(leave=leave)
        trainer = Trainer(
            default_root_dir=tmpdir,
            num_sanity_val_steps=0,
            limit_train_batches=1,
            max_epochs=6,
            callbacks=progress_bar,
        )
        trainer.fit(model)
    assert mock_progress_reset.call_count == reset_call_count


@RunIf(rich=True)
@mock.patch("pytorch_lightning.callbacks.progress.rich_progress.Progress.update")
@pytest.mark.parametrize(("refresh_rate", "expected_call_count"), ([(0, 0), (3, 7)]))
def test_rich_progress_bar_refresh_rate(progress_update, tmpdir, refresh_rate, expected_call_count):

    model = BoringModel()

    trainer = Trainer(
        default_root_dir=tmpdir,
        num_sanity_val_steps=0,
        limit_train_batches=6,
        limit_val_batches=6,
        max_epochs=1,
        callbacks=RichProgressBar(refresh_rate=refresh_rate),
    )

    trainer.fit(model)

    assert progress_update.call_count == expected_call_count


@RunIf(rich=True)
@pytest.mark.parametrize("limit_val_batches", (1, 5))
def test_rich_progress_bar_num_sanity_val_steps(tmpdir, limit_val_batches: int):
    model = BoringModel()

    progress_bar = RichProgressBar()
    num_sanity_val_steps = 3

    trainer = Trainer(
        default_root_dir=tmpdir,
        num_sanity_val_steps=num_sanity_val_steps,
        limit_train_batches=1,
        limit_val_batches=limit_val_batches,
        max_epochs=1,
        callbacks=progress_bar,
    )

    trainer.fit(model)
    assert progress_bar.progress.tasks[0].completed == min(num_sanity_val_steps, limit_val_batches)
