# future
from __future__ import annotations

# stdlib
import operator
from typing import Any
from typing import List
from typing import Optional
from typing import Tuple
from typing import Union

# third party
import numpy as np
import torch as th

# relative
from ... import lib
from ...ast.klass import pointerize_args_and_kwargs
from ...util import inherit_tags
from ..common.serde.serializable import serializable
from ..common.uid import UID
from ..node.abstract.node import AbstractNodeClient
from ..node.common.action.run_class_method_action import RunClassMethodAction
from ..pointer.pointer import Pointer
from .ancestors import AutogradTensorAncestor
from .ancestors import PhiTensorAncestor
from .fixed_precision_tensor_ancestor import FixedPrecisionTensorAncestor
from .passthrough import PassthroughTensor  # type: ignore
from .smpc.mpc_tensor import MPCTensor


class TensorPointer(Pointer):

    # Must set these at class init time despite
    # the fact that klass.Class tries to override them (unsuccessfully)
    __name__ = "TensorPointer"
    __module__ = "syft.core.tensor.tensor"

    def __init__(
        self,
        client: Any,
        id_at_location: Optional[UID] = None,
        object_type: str = "",
        tags: Optional[List[str]] = None,
        description: str = "",
        public_shape: Optional[Tuple[int, ...]] = None,
    ):

        super().__init__(
            client=client,
            id_at_location=id_at_location,
            object_type=object_type,
            tags=tags,
            description=description,
        )

        self.public_shape = public_shape

    def share(self, *parties: Tuple[AbstractNodeClient, ...]) -> MPCTensor:
        all_parties = list(parties) + [self.client]
        self_mpc = MPCTensor(secret=self, shape=self.public_shape, parties=all_parties)
        return self_mpc

    def _apply_tensor_op(self, other: Any, op_str: str) -> Any:
        # we want to get the return type which matches the attr_path_and_name
        # so we ask lib_ast for the return type name that matches out
        # attr_path_and_name and then use that to get the actual pointer klass
        # then set the result to that pointer klass

        attr_path_and_name = f"syft.core.tensor.tensor.Tensor.__{op_str}__"

        result = TensorPointer(client=self.client)

        # QUESTION can the id_at_location be None?
        result_id_at_location = getattr(result, "id_at_location", None)

        if result_id_at_location is not None:
            # first downcast anything primitive which is not already PyPrimitive
            (
                downcast_args,
                downcast_kwargs,
            ) = lib.python.util.downcast_args_and_kwargs(args=[other], kwargs={})

            # then we convert anything which isnt a pointer into a pointer
            pointer_args, pointer_kwargs = pointerize_args_and_kwargs(
                args=downcast_args,
                kwargs=downcast_kwargs,
                client=self.client,
                gc_enabled=False,
            )

            cmd = RunClassMethodAction(
                path=attr_path_and_name,
                _self=self,
                args=pointer_args,
                kwargs=pointer_kwargs,
                id_at_location=result_id_at_location,
                address=self.client.address,
            )
            self.client.send_immediate_msg_without_reply(msg=cmd)

        inherit_tags(
            attr_path_and_name=attr_path_and_name,
            result=result,
            self_obj=self,
            args=[other],
            kwargs={},
        )

        result_public_shape = None

        op = getattr(operator, op_str)

        if isinstance(other, TensorPointer):
            other_shape = other.public_shape
        elif isinstance(other, (int, float)):
            other_shape = (1,)
        elif isinstance(other, np.ndarray):
            other_shape = other.shape
        else:
            raise ValueError(f"Invalid Type for TensorPointer:{type(other)}")

        if self.public_shape is not None and other_shape is not None:
            result_public_shape = (
                op(np.empty(self.public_shape), np.empty(other_shape))
            ).shape

        result.public_shape = result_public_shape

        return result

    @staticmethod
    def _apply_op(
        self: TensorPointer,
        other: Union[TensorPointer, MPCTensor, int, float, np.ndarray],
        op_str: str,
    ) -> Union[MPCTensor, TensorPointer]:
        """Performs the operation based on op_str

        Args:
            other (Union[TensorPointer,MPCTensor,int,float,np.ndarray]): second operand.

        Returns:
            Tuple[MPCTensor,Union[MPCTensor,int,float,np.ndarray]] : Result of the operation
        """
        op = getattr(operator, op_str)

        if isinstance(other, TensorPointer) and self.client != other.client:

            parties = [self.client, other.client]

            self_mpc = MPCTensor(secret=self, shape=self.public_shape, parties=parties)
            other_mpc = MPCTensor(
                secret=other, shape=other.public_shape, parties=parties
            )

            return op(self_mpc, other_mpc)

        elif isinstance(other, MPCTensor):

            return op(other, self)

        return self._apply_tensor_op(other=other, op_str=op_str)

    def __add__(
        self, other: Union[TensorPointer, MPCTensor, int, float, np.ndarray]
    ) -> Union[TensorPointer, MPCTensor]:
        """Apply the "add" operation between "self" and "other"

        Args:
            y (Union[TensorPointer,MPCTensor,int,float,np.ndarray]) : second operand.

        Returns:
            Union[TensorPointer,MPCTensor] : Result of the operation.
        """
        return TensorPointer._apply_op(self, other, "add")

    def __sub__(
        self, other: Union[TensorPointer, MPCTensor, int, float, np.ndarray]
    ) -> Union[TensorPointer, MPCTensor]:
        """Apply the "sub" operation between "self" and "other"

        Args:
            y (Union[TensorPointer,MPCTensor,int,float,np.ndarray]) : second operand.

        Returns:
            Union[TensorPointer,MPCTensor] : Result of the operation.
        """
        return TensorPointer._apply_op(self, other, "sub")

    def __mul__(
        self, other: Union[TensorPointer, MPCTensor, int, float, np.ndarray]
    ) -> Union[TensorPointer, MPCTensor]:
        """Apply the "mul" operation between "self" and "other"

        Args:
            y (Union[TensorPointer,MPCTensor,int,float,np.ndarray]) : second operand.

        Returns:
            Union[TensorPointer,MPCTensor] : Result of the operation.
        """
        return TensorPointer._apply_op(self, other, "mul")


def to32bit(np_array: np.ndarray, verbose: bool = True) -> np.ndarray:

    if np_array.dtype == np.int64:
        if verbose:
            print("Casting internal tensor to int32")
        out = np_array.astype(np.int32)

    elif np_array.dtype == np.float64:

        if verbose:
            print("Casting internal tensor to float32")
        out = np_array.astype(np.float32)

    else:
        out = np_array

    return out


@serializable(recursive_serde=True)
class Tensor(
    PassthroughTensor,
    AutogradTensorAncestor,
    PhiTensorAncestor,
    FixedPrecisionTensorAncestor,
    # MPCTensorAncestor,
):

    __attr_allowlist__ = ["child", "tag_name", "public_shape"]

    PointerClassOverride = TensorPointer

    def __init__(
        self, child: Any, public_shape: Optional[Tuple[int, ...]] = None
    ) -> None:
        """data must be a list of numpy array"""

        if isinstance(child, list):
            child = to32bit(np.array(child), verbose=False)

        if isinstance(child, th.Tensor):
            print(
                "Converting PyTorch tensor to numpy tensor for internal representation..."
            )
            child = to32bit(child.numpy())

        if not isinstance(child, PassthroughTensor) and not isinstance(
            child, np.ndarray
        ):
            raise Exception("Data must be list or nd.array")

        if not isinstance(child, (np.ndarray, PassthroughTensor)) or (
            getattr(child, "dtype", None) != np.int32
            and getattr(child, "dtype", None) is not None
        ):
            raise TypeError(
                "You tried to pass an a tensor of type:"
                + str(type(child))
                + " with child.dtype == "
                + str(getattr(child, "dtype", None))
                + ". Syft tensor objects only support np.int32 objects at this time. Please pass in either "
                "a list of int objects or a np.int32 array. We apologise for the inconvenience and will "
                "be adding support for more types very soon!"
            )

        kwargs = {"child": child}
        super().__init__(**kwargs)

        # set public shape to be the shape of the data since we have access to it at present
        if public_shape is None:
            public_shape = tuple(self.shape)

        self.tag_name: Optional[str] = None
        self.public_shape = public_shape

    def tag(self, name: str) -> Tensor:
        self.tag_name = name
        return self

    def init_pointer(
        self,
        client: Any,
        id_at_location: Optional[UID] = None,
        object_type: str = "",
        tags: Optional[List[str]] = None,
        description: str = "",
    ) -> Pointer:

        # relative
        from .autodp.single_entity_phi import SingleEntityPhiTensor
        from .autodp.single_entity_phi import TensorWrappedSingleEntityPhiTensorPointer

        if isinstance(self.child, SingleEntityPhiTensor):
            return TensorWrappedSingleEntityPhiTensorPointer(
                entity=self.child.entity,
                client=client,
                id_at_location=id_at_location,
                object_type=object_type,
                tags=tags,
                description=description,
                min_vals=self.child.min_vals,
                max_vals=self.child.max_vals,
                scalar_manager=self.child.scalar_manager,
                public_shape=getattr(self, "public_shape", None),
            )
        else:
            return TensorPointer(
                client=client,
                id_at_location=id_at_location,
                object_type=object_type,
                tags=tags,
                description=description,
                public_shape=getattr(self, "public_shape", None),
            )
