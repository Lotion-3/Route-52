import React from 'react';
import type { LatLng, Point, Region } from './sharedTypes';
import type { Address, Camera, EdgePadding, SnapshotOptions } from './MapView.types';
import { type MapBoundaries } from './specs/NativeAirMapsModule';
import FabricMapView, { Commands as FabricCommands, type MapFabricNativeProps } from './specs/NativeComponentMapView';
import GoogleMapView, { Commands as GoogleCommands, type MapFabricNativeProps as GoogleMapFabricNativeProps } from './specs/NativeComponentGoogleMapView';
export type MapViewProps = MapFabricNativeProps | GoogleMapFabricNativeProps;
export interface FabricMapHandle {
    getCamera: () => Promise<Camera>;
    setCamera: (camera: Partial<Camera>) => void;
    animateToRegion: (region: Region, duration: number) => void;
    animateCamera: (camera: Partial<Camera>, duration: number) => void;
    getMarkersFrames: (onlyVisible: boolean) => Promise<unknown>;
    fitToElements: (edgePadding: EdgePadding, animated: boolean) => void;
    fitToSuppliedMarkers: (markers: string[], edgePadding: EdgePadding, animated: boolean) => void;
    fitToCoordinates: (coordinates: LatLng[], edgePadding: EdgePadding, animated: boolean) => void;
    getMapBoundaries: () => Promise<MapBoundaries>;
    takeSnapshot: (config: SnapshotOptions) => Promise<string>;
    getAddressFromCoordinates: (coordinate: LatLng) => Promise<Address>;
    getPointForCoordinate: (coordinate: LatLng) => Promise<Point>;
    getCoordinateForPoint: (point: Point) => Promise<LatLng>;
    setIndoorActiveLevelIndex: (activeLevelIndex: number) => void;
}
declare const createFabricMap: (ViewComponent: typeof GoogleMapView | typeof FabricMapView, Commands: typeof FabricCommands | typeof GoogleCommands) => React.ForwardRefExoticComponent<MapViewProps & React.RefAttributes<FabricMapHandle | null>>;
export default createFabricMap;
